"""DeepTutor-venv bridge: existing LlamaIndex nodes, no synthesis/query-fusion LLM."""
import contextlib
import io
import json
import re
import sys
from pathlib import Path


def execute(operation, physical_kb, query=""):
    if not re.fullmatch(r"vl-[0-9a-f]{32}", physical_kb):
        raise ValueError("invalid publication")
    from deeptutor.services.path_service import get_path_service
    from deeptutor.services.rag.provider_binding import resolve_bound_provider
    from deeptutor.services.rag.pipelines.llamaindex.pipeline import LlamaIndexPipeline
    from deeptutor.services.rag.pipelines.llamaindex.vector_store import load_index
    from deeptutor.services.rag.index_versioning import resolve_storage_dir_for_read
    base = (get_path_service().project_root / "data" / "knowledge_bases").resolve()
    if resolve_bound_provider(str(base), physical_kb) != "llamaindex":
        return {"error": "raw_provider_unsupported", "status_code":503}
    kb_dir = (base / physical_kb).resolve()
    if not kb_dir.is_relative_to(base): raise ValueError("invalid publication path")
    pipeline=LlamaIndexPipeline(str(base))
    storage=resolve_storage_dir_for_read(kb_dir, pipeline._current_signature())
    if storage is None: return {"needs_reindex":True, "status_code":409}
    storage=Path(storage).resolve()
    if not storage.is_relative_to(kb_dir): raise ValueError("invalid index path")
    index=load_index(storage)
    if operation == "manifest":
        nodes=[(node,None) for node in index.docstore.docs.values()
               if getattr(node,"ref_doc_id",None) is not None]
    elif operation == "search":
        # A plain vector retriever uses embeddings only, never query-fusion/synthesis.
        nodes=[(item.node,item.score) for item in index.as_retriever(similarity_top_k=5).retrieve(query)]
    else: raise ValueError("invalid operation")
    chunks=[]
    for node,score in nodes:
        text=getattr(node,"text",None); identifier=getattr(node,"node_id",None)
        if not isinstance(text,str) or not text.strip() or not isinstance(identifier,str) or not identifier:
            raise ValueError("invalid raw chunk")
        metadata=getattr(node,"metadata",{}) or {}
        chunks.append({"chunk_id":identifier,"content":text,"score":score,
                       "page":metadata.get("page_label",metadata.get("page"))})
    if operation=="manifest" and not chunks: raise ValueError("empty publication")
    return {"provider":"llamaindex","index_version":storage.name,
            "publication_ref":physical_kb,"chunks":chunks}


if __name__=="__main__":
    try:
        # Engine initialization may print status text; stdout is strictly our JSON protocol.
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            result=execute(*sys.argv[1:])
        encoded=json.dumps(result,ensure_ascii=False,allow_nan=False)
    except Exception:
        encoded=json.dumps({"error":"raw_retrieval_unavailable","status_code":502})
    print(encoded)
