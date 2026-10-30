from unittest.mock import AsyncMock

import pytest

from backend.services.ai.benchmark import BenchmarkRunner, BenchmarkTarget
from backend.services.ai.grounded_chat import GroundedChatRequest, GroundedChatService, RetrievedContextItem
from backend.services.ai.model_config import ModelConfig
from backend.services.ai.orchestrator import AIOrchestrator
from backend.services.ai.provider_base import LLMResult


def prepared(top_k=2):
    service=GroundedChatService(AIOrchestrator(AsyncMock()),top_k=top_k)
    return service.prepare(GroundedChatRequest("Question",[
        RetrievedContextItem("First evidence","ref-1","one.pdf",score=0.9,
                             metadata={"chunk_id":"chunk-1","document_version_id":"v1"}),
        RetrievedContextItem("Second evidence","ref-2","two.pdf",score=0.8,
                             metadata={"chunk_id":"chunk-2","document_version_id":"v2"}),
        RetrievedContextItem("Third evidence","ref-3","three.pdf",score=0.7,
                             metadata={"chunk_id":"chunk-3","document_version_id":"v3"}),
    ]))


@pytest.mark.asyncio
async def test_models_receive_identical_fixed_evidence_and_records_are_separate():
    snapshot=prepared()
    first=AsyncMock(); second=AsyncMock()
    first.generate=AsyncMock(return_value=LLMResult("success","ollama","local","A [Nguồn 1]",11,
        usage={"prompt_tokens":100,"completion_tokens":10}))
    second.generate=AsyncMock(return_value=LLMResult("success","openai","cloud","B [Nguồn 2]",22,
        usage={"prompt_tokens":100,"completion_tokens":20}))
    targets=[
        BenchmarkTarget(ModelConfig("ollama","local",temperature=0,max_tokens=200),first),
        BenchmarkTarget(ModelConfig("openai","cloud",temperature=0,max_tokens=200,
            api_key_env="OPENAI_API_KEY",allow_cloud_document_content=True,
            input_cost_per_million=1,output_cost_per_million=2),second),
    ]
    records=await BenchmarkRunner().run("q-1",snapshot,targets)
    assert first.generate.await_args.args==second.generate.await_args.args==(snapshot.prompt,snapshot.system_prompt)
    assert first.generate.await_args.kwargs==second.generate.await_args.kwargs=={"temperature":0,"max_tokens":200}
    assert [r.raw_response for r in records]==["A [Nguồn 1]","B [Nguồn 2]"]
    assert all(r.chunk_ids==("chunk-1","chunk-2") for r in records)
    assert all(r.document_version==("v1","v2") for r in records)
    assert all(r.retrieval_config=={"top_k":2,"candidate_chunks":3,"selected_chunks":2} for r in records)
    assert records[1].estimated_cost==0.00014
    assert records[0].estimated_cost is None


@pytest.mark.asyncio
async def test_raw_display_and_multi_check_evaluation_are_distinct():
    snapshot=prepared(1)
    provider=AsyncMock(); provider.generate=AsyncMock(return_value=LLMResult(
        "success","ollama","model","中文 answer [Nguồn 9]",3))
    record=(await BenchmarkRunner().run("q",snapshot,[
        BenchmarkTarget(ModelConfig("ollama","model"),provider)]))[0]
    assert record.raw_response=="中文 answer [Nguồn 9]"
    assert record.displayed_answer==record.raw_response
    assert record.quality_status=="failed" and record.display_action=="raw"
    assert record.evaluation_result["han_character_count"]==2
    assert record.evaluation_result["han_is_substantial"] is False
    assert record.evaluation_result["citation_status"]=="invalid"
    assert record.evaluation_result["passed"] is False


@pytest.mark.asyncio
async def test_api_error_keeps_schema_without_leaking_body():
    snapshot=prepared(1)
    provider=AsyncMock(); provider.generate=AsyncMock(return_value=LLMResult(
        "error","anthropic","claude","SECRET BODY",9,error_code="HTTP_503"))
    record=(await BenchmarkRunner().run("q-error",snapshot,[BenchmarkTarget(
        ModelConfig("anthropic","claude",api_key_env="ANTHROPIC_API_KEY",allow_cloud_document_content=True),provider)]))[0]
    data=record.to_dict()
    assert set(data)=={"question_id","model","provider","prompt_version","document_version",
        "retrieval_config","chunk_ids","latency","token_usage","estimated_cost","raw_response",
        "displayed_answer","evaluation_result","status","error_code","quality_status","display_action"}
    assert data["status"]=="error" and data["error_code"]=="HTTP_503"
    assert data["raw_response"]==data["displayed_answer"]==""
    assert "SECRET" not in repr(data)


@pytest.mark.asyncio
async def test_error_keeps_only_allowlisted_provider_metadata():
    snapshot=prepared(1)
    provider=AsyncMock(); provider.generate=AsyncMock(return_value=LLMResult(
        "error","openrouter","model","",7,error_code="EMPTY_RESPONSE",metadata={
            "content_type":"NoneType","content_length":0,"finish_reason":"length",
            "reasoning_present":True,"reasoning_length":500,"reasoning_tokens":1024,
            "http_status":200,"provider_response_id":"gen-123","raw_body":"SECRET"}))
    record=(await BenchmarkRunner().run("q",snapshot,[BenchmarkTarget(ModelConfig(
        "openrouter","model",api_key_env="OPENROUTER_API_KEY",
        allow_cloud_document_content=True),provider)]))[0]
    assert record.provider_metadata=={
        "content_type":"NoneType","content_length":0,"finish_reason":"length",
        "reasoning_present":True,"reasoning_length":500,"reasoning_tokens":1024,
        "http_status":200,"provider_response_id":"gen-123"}
    assert "SECRET" not in repr(record.to_dict())


def test_top_k_is_configurable_and_defaults_to_three():
    default=prepared(3)
    one=GroundedChatService(AIOrchestrator(AsyncMock())).prepare(GroundedChatRequest("Q",[
        RetrievedContextItem("one","1",score=0.9),RetrievedContextItem("two","2",score=0.8)]),top_k=1)
    assert default.retrieval_config=={"top_k":3,"candidate_chunks":3,"selected_chunks":3}
    assert one.chunk_ids==("1",) and one.retrieval_config["top_k"]==1


@pytest.mark.asyncio
async def test_runner_blocks_cloud_target_before_provider_by_default():
    snapshot=prepared(1)
    provider=AsyncMock(); provider.generate=AsyncMock()
    record=(await BenchmarkRunner().run("q",snapshot,[BenchmarkTarget(
        ModelConfig("openai","gpt-test",api_key_env="OPENAI_API_KEY"),provider)]))[0]
    assert record.error_code=="CLOUD_CONTENT_DISABLED" and record.raw_response==""
    provider.generate.assert_not_awaited()
