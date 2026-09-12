"""Generate collection and service indexes from public document metadata."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path, PurePosixPath
import posixpath
import sys
from typing import Any, Iterable, Mapping

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.docs.content import Document, iter_public_documents, load_taxonomy


def _relative_link(index_path: PurePosixPath, document: Document) -> str:
    return posixpath.relpath(
        document.relative_path.as_posix(), start=index_path.parent.as_posix()
    )


def _document_line(index_path: PurePosixPath, document: Document) -> str:
    title = document.metadata["title"]
    description = document.metadata["description"]
    return f"- [{title}]({_relative_link(index_path, document)}) — {description}"


def _front_matter(title: str, description: str) -> str:
    return (
        "---\n"
        f"title: {title}\n"
        f"description: {description}\n"
        "---\n\n"
    )


def build_index_pages(
    documents: Iterable[Document], taxonomy: Mapping[str, Any]
) -> dict[PurePosixPath, str]:
    """Return virtual Markdown pages keyed by their docs-relative path."""
    docs = sorted(documents, key=lambda item: str(item.metadata.get("title", "")).casefold())
    pages: dict[PurePosixPath, str] = {}
    collections = taxonomy.get("collections", {})

    for document_type, config in collections.items():
        index_path = PurePosixPath(config["path"]) / "index.md"
        matching = [doc for doc in docs if doc.metadata.get("document_type") == document_type]
        body = _front_matter(config["title"], config["description"])
        body += f"# {config['title']}\n\n{config['description']}\n\n"
        if matching:
            body += "\n".join(_document_line(index_path, doc) for doc in matching) + "\n"
        else:
            body += "아직 등록된 문서가 없습니다.\n"
        pages[index_path] = body

    by_service: dict[str, list[Document]] = defaultdict(list)
    for document in docs:
        for service in document.metadata.get("services", []):
            by_service[service].append(document)

    services_path = PurePosixPath("services/index.md")
    service_lines: list[str] = []
    for service, label in taxonomy.get("services", {}).items():
        count = len(by_service.get(service, []))
        service_lines.append(f"- [{label}]({service}.md) ({count})")
        page_path = PurePosixPath(f"services/{service}.md")
        page = _front_matter(label, f"{label} 관련 문서를 모아 봅니다.")
        page += f"# {label}\n\n"
        matching = by_service.get(service, [])
        if not matching:
            page += "아직 등록된 문서가 없습니다.\n"
        else:
            for document_type, collection in collections.items():
                typed = [
                    doc for doc in matching if doc.metadata.get("document_type") == document_type
                ]
                if typed:
                    page += f"## {collection['title']}\n\n"
                    page += "\n".join(_document_line(page_path, doc) for doc in typed) + "\n\n"
        pages[page_path] = page

    service_index = _front_matter("서비스별 찾기", "Azure 서비스별로 문서를 탐색합니다.")
    service_index += "# 서비스별 찾기\n\nAzure 서비스별로 문서를 탐색합니다.\n\n"
    service_index += "\n".join(service_lines) + "\n"
    pages[services_path] = service_index
    return pages


def write_generated_pages(repo_root: Path | None = None) -> None:
    """Write virtual pages through mkdocs-gen-files during a site build."""
    import mkdocs_gen_files

    root = repo_root or REPO_ROOT
    taxonomy = load_taxonomy(root / "docs-taxonomy.yml")
    documents = list(iter_public_documents(root / "docs", taxonomy))
    for path, content in build_index_pages(documents, taxonomy).items():
        with mkdocs_gen_files.open(path.as_posix(), "w") as generated:
            generated.write(content)


if __name__ == "__main__" or __name__.startswith("<"):
    write_generated_pages()
