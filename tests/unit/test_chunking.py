"""Chunking — the extraction PROMPT contract, the inline truncation guard, and the language seam.

Three ratified changes are pinned here (all 2026-08-19, all measured in
``data/dec_p0/extraction_blindness.{md,json}``):

* **D13** — the no-number clause added to ``_PROP_SYSTEM``. The prompt was measured NUMBER-ANCHORED
  (quantified sentences survived to a proposition 60.3% of the time, mechanism 40.0%, substitution
  32.3%, conditional 20.5%, risk/scenario 20.2%); the amendment lifted conditional to 78.9%/52.6%
  and risk to 68.9%/60.0% over two independent runs. The old asks must survive the addition.
* **D13 rider / D-XB-4** — the inline path had NO ``stop_reason`` guard: a max_tokens-cut array parses
  to ``[]`` and the whole ~5,000-char window silently became one "proposition". It now splits once and
  retries both halves, exactly as the batch path does, and tallies every event.
* **D13 rider 2 / D-XB-5** — ``conab`` (pt) and ``fnc`` (es) props are English over original-language
  spans; the corpus stamped them ``lang="en", translated=False``.
"""
from __future__ import annotations

from datetime import date

import pytest
from leviathan.graphrag import chunking as ch


# ── D13: the prompt contract ───────────────────────────────────────────────────────────────────────
class TestPropSystemPrompt:
    def test_new_clauses_are_present(self) -> None:
        """The measured amendment's vocabulary — the classes the extraction was blind to."""
        p = ch._PROP_SYSTEM
        assert "A statement carrying NO number is still a fact" in p
        for ask in ("CONDITIONAL", "RISK / SCENARIO", "MECHANISM", "SUBSTITUTION", "ATTRIBUTED"):
            assert ask in p, f"the {ask} ask is missing from _PROP_SYSTEM"
        # the shape-carrying cues the probe measured, not just the class names
        for cue in ("if X ... then Y", "upside risk", "because / driven by", "price-relationship",
                    "keep who said it"):
            assert cue in p, f"the '{cue}' cue is missing from _PROP_SYSTEM"

    def test_the_old_asks_survive(self) -> None:
        """D13 ADDS; it removes nothing. The dated-fact discipline is the whole provenance contract."""
        p = ch._PROP_SYSTEM
        assert "atomic, self-contained" in p and "PROPOSITIONS" in p
        assert '{"proposition": str, "verbatim_span": str, "event_date": str, ' \
               '"event_date_precision": str}' in p
        assert "each proposition states ONE fact" in p and "resolve pronouns/ellipsis" in p
        assert "EXACT substring of the passage" in p and "do not paraphrase" in p
        assert "WHEN THE EVENT ITSELF OCCURRED OR WILL OCCUR" in p
        assert "NOT the report's own date" in p
        assert "day|month|quarter|year" in p
        assert "Skip pure boilerplate" in p
        assert "If the passage has no extractable facts, return []." in p

    def test_the_refusal_stays_last(self) -> None:
        """The empty-array refusal must remain the closing instruction, not be buried mid-prompt."""
        assert ch._PROP_SYSTEM.rstrip().endswith("If the passage has no extractable facts, return [].")

    def test_batch_and_inline_send_the_same_system_prompt(self) -> None:
        """The corpus-minting path imports THIS constant; a fork would make the measurement a lie."""
        from leviathan.graphrag import evidence_batch as eb
        assert eb.ch._PROP_SYSTEM is ch._PROP_SYSTEM
        assert eb._MAX_OUTPUT_TOKENS == ch._MAX_OUTPUT_TOKENS   # the ceiling the split-retry assumes


# ── D-XB-4: the inline truncation guard ────────────────────────────────────────────────────────────
_OK_JSON = '[{"proposition": "Brazil arabica output fell in 2021.", "verbatim_span": "%s", ' \
           '"event_date": "2021", "event_date_precision": "year"}]'


class _Bedrock:
    """Fake bedrock-runtime. `stop_reasons` is consumed one call at a time; text mirrors the input so
    the returned span is locatable in full_text (the production offset path)."""

    def __init__(self, stop_reasons: list[str]) -> None:
        self.stop_reasons, self.calls = list(stop_reasons), []

    def converse(self, **kw):
        text = kw["messages"][0]["content"][0]["text"]
        self.calls.append(text)
        stop = self.stop_reasons.pop(0) if self.stop_reasons else "end_turn"
        body = "" if stop == "max_tokens" else _OK_JSON % text.split("\n")[0][:40]
        return {"stopReason": stop, "output": {"message": {"content": [{"text": body}]}}}


def _doc(n_paras: int = 6) -> str:
    return "\n\n".join(f"Paragraph {i} on Brazilian arabica coffee, frost damage and export flows, "
                       f"with enough prose to make a real window." for i in range(n_paras))


def _kw(text: str, **over):
    base = dict(full_text=text, source_key="text/source=usda_gain_corn/x/document.json",
                source="usda_gain_corn", document_date=date(2021, 7, 20), lang="en",
                extraction_method="pdfplumber", doc_id="d1")
    base.update(over)
    return base


@pytest.fixture(autouse=True)
def _zero_tally():
    ch._reset_inline_truncations()
    yield
    ch._reset_inline_truncations()


class TestInlineTruncationGuard:
    def test_truncated_window_is_split_once_and_both_halves_retried(self, caplog) -> None:
        text = _doc()
        bed = _Bedrock(["max_tokens", "end_turn", "end_turn"])
        with caplog.at_level("WARNING"):
            chunks = ch.propositional_chunks(**_kw(text), bedrock=bed, max_block_chars=100_000)

        assert len(bed.calls) == 3                                   # 1 truncated + 2 halves
        assert bed.calls[1] + bed.calls[2] == bed.calls[0]           # no character dropped by the split
        assert len(chunks) == 2                                      # one prop recovered per half
        assert ch.INLINE_TRUNCATIONS["windows_truncated"] == 1
        assert ch.INLINE_TRUNCATIONS["halves_retried"] == 2
        assert ch.INLINE_TRUNCATIONS["halves_still_truncated"] == 0
        assert ch.INLINE_TRUNCATIONS["blocks_fallback_whole"] == 0   # nothing degraded to a whole block
        assert "output ceiling" in caplog.text                       # loud, not silent

    def test_a_half_that_truncates_again_is_counted_not_re_split(self, caplog) -> None:
        """One split and one only — the batch path's rule. The lost half is TALLIED, never silent."""
        bed = _Bedrock(["max_tokens", "max_tokens", "end_turn"])
        with caplog.at_level("WARNING"):
            chunks = ch.propositional_chunks(**_kw(_doc()), bedrock=bed, max_block_chars=100_000)

        assert len(bed.calls) == 3                                   # NOT re-split into quarters
        assert ch.INLINE_TRUNCATIONS["halves_still_truncated"] == 1
        assert len(chunks) == 1                                      # only the surviving half's prop
        assert "truncated AGAIN" in caplog.text

    def test_a_fully_lost_window_falls_back_to_the_block_but_is_now_counted(self, caplog) -> None:
        """The pre-D13 behaviour (whole block becomes one 'proposition') is preserved so output stays
        contract-valid — but it no longer happens invisibly."""
        bed = _Bedrock(["max_tokens", "max_tokens", "max_tokens"])
        with caplog.at_level("WARNING"):
            chunks = ch.propositional_chunks(**_kw(_doc()), bedrock=bed, max_block_chars=100_000)

        assert len(chunks) == 1 and len(chunks[0].proposition) > 200  # the whole-block fallback
        assert ch.INLINE_TRUNCATIONS["blocks_fallback_whole"] == 1
        assert ch.INLINE_TRUNCATIONS["windows_truncated"] == 1
        assert "falling back to the whole" in caplog.text

    def test_an_untruncated_window_costs_exactly_one_call(self) -> None:
        bed = _Bedrock(["end_turn"])
        chunks = ch.propositional_chunks(**_kw(_doc()), bedrock=bed, max_block_chars=100_000)
        assert len(bed.calls) == 1 and len(chunks) == 1
        assert ch.INLINE_TRUNCATIONS == {"windows_truncated": 0, "halves_retried": 0,
                                         "halves_still_truncated": 0, "blocks_fallback_whole": 0}

    def test_provider_helpers_report_the_stop_reason(self) -> None:
        """The gate itself: `stop_reason` decides truncation BEFORE the parse, because a cut array can
        still parse on an inner ']' and look like a legitimate partial."""
        assert ch._haiku_propositions(_Bedrock(["max_tokens"]), "x", "m") == ([], True)
        items, truncated = ch._haiku_propositions(_Bedrock(["end_turn"]), "x", "m")
        assert truncated is False and len(items) == 1

    def test_a_provider_exception_is_not_a_truncation(self) -> None:
        class _Boom:
            def converse(self, **kw):
                raise RuntimeError("throttled")

        assert ch._haiku_propositions(_Boom(), "x", "m") == ([], False)

    def test_anthropic_path_reads_stop_reason_too(self) -> None:
        class _Block:
            type, text = "text", _OK_JSON % "span"

        class _Client:
            def __init__(self, stop): self.messages, self._stop = self, stop
            def create(self, **kw):
                import types
                return types.SimpleNamespace(content=[_Block()], stop_reason=self._stop)

        assert ch._anthropic_propositions(_Client("max_tokens"), "x", "m")[1] is True
        assert ch._anthropic_propositions(_Client("end_turn"), "x", "m")[1] is False

    def test_split_block_never_drops_a_character(self) -> None:
        for text in ("a b c d e f g h", "para one\n\npara two\n\npara three", "x" * 101,
                     "line one\nline two\nline three"):
            halves = ch._split_block(text)
            assert len(halves) == 2 and "".join(halves) == text


# ── D-XB-5: the language seam ──────────────────────────────────────────────────────────────────────
class TestSourceLanguage:
    def test_the_map_holds_the_measured_non_english_sources(self) -> None:
        assert ch._SOURCE_LANG == {"conab": "pt", "fnc": "es"}       # 55 + 56 = 111 documents

    def test_sagis_is_deliberately_english(self) -> None:
        """SAGIS publishes bilingual EN/AF, so the English text IS in the source and a proposition
        drawn from it is not a translation. Documented decision, not an oversight."""
        assert "sagis_cec" not in ch._SOURCE_LANG
        assert ch._doc_lang("sagis_cec", "en") == "en"

    def test_unknown_source_keeps_the_callers_lang(self) -> None:
        assert ch._doc_lang("usda_wasde", "en") == "en"
        assert ch._doc_lang("brand_new_source", "fr") == "fr"        # caller's value wins when unmapped
        assert ch._doc_lang(None, None) == "en"                      # and "en" is the floor

    def test_chunk_document_stamps_the_source_language_but_never_translated(self) -> None:
        """This path's proposition IS the verbatim window — pt text under lang='pt' is not a translation."""
        rows = ch.chunk_document(**_kw("Os numeros indicam uma influencia da bienalidade positiva.",
                                       source="conab", source_key="text/source=conab/x/document.json"))
        assert rows and all(c.lang == "pt" and c.translated is False for c in rows)

    def test_propositional_chunks_marks_a_translated_proposition(self) -> None:
        """Haiku returns ENGLISH props over a Portuguese span: lang = ORIGINAL, translated = True."""
        bed = _Bedrock(["end_turn"])
        rows = ch.propositional_chunks(**_kw(_doc(), source="conab",
                                             source_key="text/source=conab/x/document.json"),
                                       bedrock=bed, max_block_chars=100_000)
        assert rows and all(c.lang == "pt" and c.translated is True for c in rows)

    def test_english_sources_are_untouched(self) -> None:
        bed = _Bedrock(["end_turn"])
        rows = ch.propositional_chunks(**_kw(_doc()), bedrock=bed, max_block_chars=100_000)
        assert rows and all(c.lang == "en" and c.translated is False for c in rows)
