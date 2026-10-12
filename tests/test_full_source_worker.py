import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock
from deeptutor_integration.full_source_worker import execute


def test_bridge_returns_complete_nodes_and_uses_plain_retrieval(tmp_path,monkeypatch):
    base=tmp_path/"data"/"knowledge_bases"; kb="vl-"+"a"*32; storage=base/kb/"version-test"; storage.mkdir(parents=True)
    node=SimpleNamespace(node_id="real",ref_doc_id="document",text="full text "*60,metadata={"page":2})
    index=MagicMock(); index.docstore.docs={"real":node}
    index.as_retriever.return_value.retrieve.return_value=[SimpleNamespace(node=node,score=0.8)]
    modules={
        "deeptutor.services.path_service":{"get_path_service":lambda:SimpleNamespace(project_root=tmp_path)},
        "deeptutor.services.rag.provider_binding":{"resolve_bound_provider":lambda *a:"llamaindex"},
        "deeptutor.services.rag.pipelines.llamaindex.pipeline":{"LlamaIndexPipeline":lambda *a:SimpleNamespace(_current_signature=lambda:None)},
        "deeptutor.services.rag.pipelines.llamaindex.vector_store":{"load_index":lambda *a:index},
        "deeptutor.services.rag.index_versioning":{"resolve_storage_dir_for_read":lambda *a:storage},
    }
    for name,attributes in modules.items():
        parts=name.split(".")
        for i in range(1,len(parts)+1):
            module_name=".".join(parts[:i])
            if module_name not in sys.modules:
                module=ModuleType(module_name); module.__path__=[]; monkeypatch.setitem(sys.modules,module_name,module)
        module=ModuleType(name)
        for key,value in attributes.items(): setattr(module,key,value)
        monkeypatch.setitem(sys.modules,name,module)
    manifest=execute("manifest",kb)
    raw=execute("search",kb,"question")
    assert manifest["chunks"][0]["content"]==node.text==raw["chunks"][0]["content"]
    assert len(raw["chunks"][0]["content"])>200
    index.as_retriever.assert_called_once_with(similarity_top_k=5)
    index.as_query_engine.assert_not_called()
