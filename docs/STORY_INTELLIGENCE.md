# Story Intelligence (Timeline, Cross-Source Comparison, Coverage Perspective, Why This Matters)

Roadmap sections 27, 28, 29, and 30 (Phase 5 "Advanced AI"). Built as a
single consolidated feature since all four operate on the same input (a
story's articles) and are generated together to control LLM call volume —
see "Why one call, not four" below.

## What's generated

For each **"major" story** (3+ articles — a stricter bar than the 2+ used
for the basic AI summary, since this is richer, more expensive-to-generate
content meant for genuinely well-corroborated stories):

- **Timeline** (#27) — a short chronological narrative (2-4 sentences) of
  how coverage developed, built from the story's articles sorted by
  `published_at`. Deliberately **not** forced into the roadmap's example
  stage taxonomy ("Initial announcement → Government response → Company
  response → ...") — that arc fits policy/finance stories well but not,
  say, a sports or entertainment story. The narrative emerges from what
  the articles actually say, not a fixed template.
- **Coverage Comparison** (#28) — one line per source describing what
  angle/focus that source's coverage emphasized (e.g. "Reuters: economic
  impact"). Matches the roadmap's own example format.
- **Coverage Perspective** (#29) — a richer per-source pass: apparent
  tone (neutral/urgent/critical/sympathetic/...) plus which topics,
  entities, or word choices each source emphasized. The prompt explicitly
  forbids presenting this as a bias determination and requires the exact
  closing sentence "This is automated analysis of language patterns, not
  a definitive assessment of editorial bias" — verified live that the
  model reproduces it verbatim, not paraphrased. The UI repeats a
  shortened version of this disclaimer as a caption above the content too,
  so it isn't only visible if a reader scrolls to the end of the text.
- **Why This Matters** (#30) — 2-3 concise sentences on the story's
  significance/likely consequences, grounded in the articles.

## How it's generated

`langchain_config.generate_story_extras(story_articles)` — one Groq call
with a single prompt asking for all four sections under markdown headers
(`## Timeline`, `## Coverage Comparison`, `## Coverage Perspective`,
`## Why This Matters`), parsed back into a dict by `_parse_story_extras`.
Verified live: real 3-article test stories produced accurate chronological
ordering, source-specific focus descriptions, tone/emphasis analysis with
the disclaimer intact, and grounded significance summaries.

## Why one call, not four

The roadmap lists these as four separate features, but implementing them
as four separate Groq calls per major story would quadruple LLM cost/
latency for no real benefit — they're all synthesizing the same input
(the same articles) into different lenses on the same analysis. One call
with a structured multi-section prompt gets all four for the price of one.

## Caching, same pattern as AI summaries

Generated once per story, cached in `stories.timeline` /
`stories.coverage_comparison` / `stories.coverage_perspective` /
`stories.why_matters`, and never regenerated:
`pipeline.ingest._generate_story_extras` checks `db.get_story(story_id)`
for an existing `why_matters` value before calling Groq, and
`db.set_story_extras` only touches columns it's given a non-empty value
for — a story's existing cached analysis is never clobbered by a later
cycle that didn't regenerate it.

## Eligibility bars, summarized

| Content | Minimum articles | Function |
|---|---|---|
| Basic bullet summary | 2 | `pipeline.ingest._generate_story_summaries` |
| Timeline / comparison / perspective / why-matters | 3 | `pipeline.ingest._generate_story_extras` |

A 2-article story gets a summary only. A 3+-article story gets both.

## Where this shows up in the UI

`app.py`'s `render_story_card` (the shared component used by Home, Latest
Stories, and Saved) puts Timeline/Coverage Comparison/Coverage Perspective
inside one "Timeline, comparison & perspective" expander, and Why This
Matters inline as a highlighted line under the summary. The Coverage
Perspective sub-section always shows its own caption disclaimer
immediately above the content, independent of whatever the model itself
generated, as a second line of defense against the disclaimer being lost
if a future prompt change ever drops it.

## What's not built from the roadmap's Phase 5 list

- **Fact-check / cross-source verification (#31)** — deliberately not
  attempted in this pass. The roadmap itself is explicit that this needs
  real care to avoid an LLM's judgment being presented as definitive fact,
  and that's a bigger design conversation than "add another cached Groq
  call." Left for a dedicated pass.
- **News chatbot / RAG (#25/#26)** — the project owner has chosen
  TF-IDF-only retrieval for when that phase is built, but it hasn't been
  built yet; a bigger scope than fits alongside this round's work.

## Related work built alongside this

- **Related stories** — `db.get_related_stories(story_id)` finds other
  stories sharing extracted entities with this one, ranked by how many
  they share. Reuses Phase 2's entity data rather than needing new
  infrastructure; shown as a small list (titles + sources, not clickable
  jumps, since there's no per-story routing yet — see PROJECT_AUDIT.md's
  Technical Debt) inside its own expander on every story card.

## Testing

`tests/test_langchain_config.py` covers `_parse_story_extras` (section
splitting including Coverage Perspective, missing sections) and
`generate_story_extras` (chronological ordering, response parsing, mocked
LLM call). `tests/test_ingest.py` covers the eligibility/caching logic for
both `_generate_story_summaries` and `_generate_story_extras`.
`tests/test_db.py` covers `set_story_extras` (including
`coverage_perspective`), the `story_extras` parameter on `store_articles`,
and `get_related_stories`' entity-overlap ranking.
