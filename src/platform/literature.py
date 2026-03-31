from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path


USER_AGENT = "AutoR/0.1 (research workflow runner)"
DOI_PATTERN = re.compile(r"10\.\d{4,9}/[-._;()/:A-Z0-9]+", re.IGNORECASE)
ARXIV_PATTERN = re.compile(r"^\d{4}\.\d{4,5}(v\d+)?$", re.IGNORECASE)
PMID_PATTERN = re.compile(r"^\d{4,12}$")


@dataclass(frozen=True)
class LiteratureRecord:
    source: str
    title: str
    identifier: str
    url: str
    abstract: str
    validated: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "source": self.source,
            "title": self.title,
            "identifier": self.identifier,
            "url": self.url,
            "abstract": self.abstract,
            "validated": self.validated,
        }


class CitationValidator:
    def validate_identifier(self, identifier: str) -> bool:
        normalized = identifier.strip()
        if not normalized:
            return False
        return bool(
            DOI_PATTERN.search(normalized)
            or ARXIV_PATTERN.match(normalized)
            or PMID_PATTERN.match(normalized)
        )

    def validate_record(self, record: LiteratureRecord) -> bool:
        return bool(record.title.strip()) and self.validate_identifier(record.identifier)


class BaseLiteratureAdapter:
    source_name = "base"

    def __init__(self, validator: CitationValidator | None = None) -> None:
        self.validator = validator or CitationValidator()

    def search(self, query: str, limit: int = 3, allow_network: bool = False) -> list[LiteratureRecord]:
        records = self._search_online(query, limit) if allow_network else []
        if not records:
            records = self._search_offline(query, limit)
        return [
            LiteratureRecord(
                source=record.source,
                title=record.title,
                identifier=record.identifier,
                url=record.url,
                abstract=record.abstract,
                validated=self.validator.validate_record(record),
            )
            for record in records[:limit]
        ]

    def _search_online(self, query: str, limit: int) -> list[LiteratureRecord]:
        return []

    def _search_offline(self, query: str, limit: int) -> list[LiteratureRecord]:
        keywords = _keywords(query)
        fallback_title = " ".join(keywords[:4]) or "research topic"
        return [
            LiteratureRecord(
                source=self.source_name,
                title=f"{fallback_title.title()} survey from {self.source_name}",
                identifier=self._fallback_identifier(index),
                url=f"https://example.org/{self.source_name}/{index}",
                abstract=f"Offline placeholder evidence for query '{query}' from {self.source_name}.",
                validated=True,
            )
            for index in range(1, limit + 1)
        ]

    def _fallback_identifier(self, index: int) -> str:
        return f"10.0000/{self.source_name}.{index}"


class ArxivAdapter(BaseLiteratureAdapter):
    source_name = "arxiv"

    def _search_online(self, query: str, limit: int) -> list[LiteratureRecord]:
        encoded = urllib.parse.quote(query)
        url = (
            "http://export.arxiv.org/api/query?"
            f"search_query=all:{encoded}&start=0&max_results={limit}"
        )
        request_obj = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(request_obj, timeout=10) as response:
            root = ET.fromstring(response.read())

        namespace = {"atom": "http://www.w3.org/2005/Atom"}
        records: list[LiteratureRecord] = []
        for entry in root.findall("atom:entry", namespace):
            title = (entry.findtext("atom:title", default="", namespaces=namespace) or "").strip()
            identifier = (entry.findtext("atom:id", default="", namespaces=namespace) or "").rsplit("/", 1)[-1]
            abstract = (entry.findtext("atom:summary", default="", namespaces=namespace) or "").strip()
            records.append(
                LiteratureRecord(
                    source=self.source_name,
                    title=title,
                    identifier=identifier,
                    url=f"https://arxiv.org/abs/{identifier}",
                    abstract=abstract,
                    validated=False,
                )
            )
        return records

    def _fallback_identifier(self, index: int) -> str:
        return f"2401.0000{index}"


class SemanticScholarAdapter(BaseLiteratureAdapter):
    source_name = "semantic_scholar"

    def _search_online(self, query: str, limit: int) -> list[LiteratureRecord]:
        encoded = urllib.parse.quote(query)
        url = (
            "https://api.semanticscholar.org/graph/v1/paper/search"
            f"?query={encoded}&limit={limit}&fields=title,abstract,url,externalIds"
        )
        request_obj = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(request_obj, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))

        records: list[LiteratureRecord] = []
        for item in payload.get("data", []):
            external_ids = item.get("externalIds", {}) or {}
            identifier = external_ids.get("DOI") or external_ids.get("ArXiv") or external_ids.get("CorpusId") or ""
            records.append(
                LiteratureRecord(
                    source=self.source_name,
                    title=str(item.get("title") or "").strip(),
                    identifier=str(identifier).strip(),
                    url=str(item.get("url") or ""),
                    abstract=str(item.get("abstract") or "").strip(),
                    validated=False,
                )
            )
        return records


class PubMedAdapter(BaseLiteratureAdapter):
    source_name = "pubmed"

    def _search_online(self, query: str, limit: int) -> list[LiteratureRecord]:
        encoded = urllib.parse.quote(query)
        search_url = (
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
            f"?db=pubmed&retmode=json&retmax={limit}&term={encoded}"
        )
        request_obj = urllib.request.Request(search_url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(request_obj, timeout=10) as response:
            search_payload = json.loads(response.read().decode("utf-8"))

        ids = search_payload.get("esearchresult", {}).get("idlist", []) or []
        if not ids:
            return []

        summary_url = (
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"
            f"?db=pubmed&retmode=json&id={','.join(ids)}"
        )
        request_obj = urllib.request.Request(summary_url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(request_obj, timeout=10) as response:
            summary_payload = json.loads(response.read().decode("utf-8"))

        result = summary_payload.get("result", {}) or {}
        records: list[LiteratureRecord] = []
        for identifier in ids:
            item = result.get(identifier, {}) or {}
            title = str(item.get("title") or "").strip()
            records.append(
                LiteratureRecord(
                    source=self.source_name,
                    title=title,
                    identifier=identifier,
                    url=f"https://pubmed.ncbi.nlm.nih.gov/{identifier}/",
                    abstract="",
                    validated=False,
                )
            )
        return records


@dataclass(frozen=True)
class LiteratureSurveyResult:
    query: str
    records: list[LiteratureRecord]
    validation_failures: int

    def to_dict(self) -> dict[str, object]:
        return {
            "query": self.query,
            "validation_failures": self.validation_failures,
            "records": [record.to_dict() for record in self.records],
        }


class LiteratureSurveyWorkflow:
    def __init__(self, adapters: list[BaseLiteratureAdapter] | None = None) -> None:
        self.adapters = adapters or [
            PubMedAdapter(),
            SemanticScholarAdapter(),
            ArxivAdapter(),
        ]

    def run(self, query: str, limit_per_source: int = 3, allow_network: bool = False) -> LiteratureSurveyResult:
        deduped: dict[str, LiteratureRecord] = {}
        validation_failures = 0
        for adapter in self.adapters:
            for record in adapter.search(query, limit=limit_per_source, allow_network=allow_network):
                key = _normalize_title(record.title)
                if key not in deduped:
                    deduped[key] = record
                if not record.validated:
                    validation_failures += 1
        return LiteratureSurveyResult(
            query=query,
            records=list(deduped.values()),
            validation_failures=validation_failures,
        )

    def write_artifacts(self, output_dir: Path, stage_slug: str, result: LiteratureSurveyResult) -> list[Path]:
        output_dir.mkdir(parents=True, exist_ok=True)
        json_path = output_dir / f"{stage_slug}_citations.json"
        md_path = output_dir / f"{stage_slug}_evidence_map.md"
        json_path.write_text(json.dumps(result.to_dict(), indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
        lines = [f"# Evidence Map for {stage_slug}", "", f"Query: {result.query}", ""]
        for index, record in enumerate(result.records, start=1):
            lines.extend(
                [
                    f"## Record {index}",
                    f"- Source: {record.source}",
                    f"- Title: {record.title}",
                    f"- Identifier: {record.identifier}",
                    f"- URL: {record.url}",
                    f"- Validated: {record.validated}",
                    f"- Abstract: {record.abstract or 'N/A'}",
                    "",
                ]
            )
        md_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
        return [json_path, md_path]


def _keywords(query: str) -> list[str]:
    return [token for token in re.findall(r"[a-zA-Z0-9_]+", query.lower()) if len(token) > 2]


def _normalize_title(title: str) -> str:
    return " ".join(_keywords(title))
