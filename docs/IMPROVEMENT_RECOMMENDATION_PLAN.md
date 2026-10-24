# Improvement Recommendation Plan (Phase 1: Pre-Launch Polish)

This plan details the essential, fast-turnaround improvements required to resolve visual defects, eliminate screen clutter, clarify user-facing metrics, and ensure a resilient, cost-conscious initial launch.

---

## 1. Overview & Priority Matrix

| Priority | Area | Defect / Opportunity | Target Files | Estimated Effort |
| :--- | :--- | :--- | :--- | :--- |
| **P0** | Database & Retrieval | Missing cover art and studio metadata | `backend/rag_pipeline/helper/retrieval.py`<br>`backend/rag_pipeline/helper/ranking.py` | 1 hour |
| **P0** | Serialisation & UI | Decimal year, episodes, and review scores | `backend/telemetry/logger.py`<br>`frontend/src/components/chat/AnimeCard.tsx` | 1 hour |
| **P0** | UI / Clarity | Ambiguous rating percentage badge | `frontend/src/components/chat/AnimeCard.tsx` | 30 mins |
| **P1** | UX & LLM Cost | Per-card on-demand curator notes (zero upfront cost) | `frontend/src/components/chat/AnimeCard.tsx`<br>`backend/rag_pipeline/orchestrator.py` | 1.5 hours |
| **P1** | Markdown Parser | Broken unicode bullets (`•`) & citation tags | `frontend/src/components/chat/ConciergePitch.tsx` | 1 hour |
| **P1** | Guardrails | Empty candidate dropout on genre exclusions | `backend/rag_pipeline/orchestrator.py`<br>`backend/rag_pipeline/helper/ranking.py` | 2 hours |
| **P2** | Feature | Immediate "Load More" pagination button | `frontend/src/routes/ChatPage.tsx`<br>`backend/rag_pipeline/orchestrator.py` | 2 hours |

---

## 2. Detailed Technical Actions

### Task 1.1 (P0): Fix Missing Cover Art & Case-Sensitivity Dropouts
- **Problem**: In `backend/rag_pipeline/helper/retrieval.py` (lines 175 and 233), `core.coverImage_large` and `core.title_userPreferred` are selected without double-quoted aliases. PostgreSQL folds unquoted column names to lowercase (`coverimage_large`). In `backend/rag_pipeline/helper/ranking.py` (lines 160 to 186), key lookups check camelCase `'coverImage_large' in row`. The case mismatch causes Python to discard the URL and replace it with `None`, forcing `AnimeCard.tsx` to render the `<ImageOff /> No Cover` placeholder.
- **Implementation**:
  1. In `backend/rag_pipeline/helper/retrieval.py`, add explicit double quotes to aliases:
     ```sql
     core.coverImage_large AS "coverImage_large",
     core.title_userPreferred AS "title_userPreferred",
     content.isAdult AS "isAdult"
     ```
  2. In `backend/rag_pipeline/helper/ranking.py` (`Ranker.merge_deduplicate`), make dictionary key lookup case-insensitive:
     ```python
     lower_row = {k.lower(): v for k, v in row.items()} if hasattr(row, "items") else {}
     row_dict = {c: lower_row.get(c.lower()) for c in col}
     ```
  3. In `frontend/src/components/chat/AnimeCard.tsx`, add `referrerPolicy="no-referrer"` to the `<img />` tag to prevent third-party CDNs (e.g. AniList image hosts) from rejecting requests with HTTP 403.

---

### Task 1.2 (P0): Fix Decimal Formatting on Release Year, Episodes, and Scores
- **Problem**: The database schema in `backend/data_pipeline/helper/database.py` defines `seasonYear` and `episodes` as `NUMERIC`. When fetched via `psycopg2`, they arrive as Python `decimal.Decimal`. In `backend/telemetry/logger.py`, `sanitize_for_json` lacks a `decimal.Decimal` handler and falls back to `str(obj)`, emitting `"2011.0"` and `"26.0"`. React renders these strings directly.
- **Implementation**:
  1. In `backend/telemetry/logger.py` (`sanitize_for_json`), add decimal conversion:
     ```python
     import decimal

     if isinstance(obj, decimal.Decimal):
         f_val = float(obj)
         if f_val.is_integer():
             return int(f_val)
         return f_val
     ```
  2. In `frontend/src/components/chat/AnimeCard.tsx`, defensively format integer values:
     ```tsx
     const displayYear = anime.seasonYear ? Math.round(Number(anime.seasonYear)) : null;
     const displayEpisodes = anime.episodes ? Math.round(Number(anime.episodes)) : null;
     ```

---

### Task 1.3 (P0): Clarify Ambiguous Rating Badge
- **Problem**: The raw percentage badge (e.g. `81.0%` or `69.0%`) positioned directly beside the title leads users to believe it represents AI match confidence rather than the community review rating.
- **Implementation**:
  1. In `frontend/src/components/chat/AnimeCard.tsx`, update the badge presentation to denote public community rating clearly:
     ```tsx
     {score !== null && score !== undefined && (
       <div className="shrink-0" title={`AniList Community Rating: ${Math.round(Number(score))}%`}>
         <Badge variant={getScoreVariant(score)} size="sm">
           ★ {Math.round(Number(score))}%
         </Badge>
       </div>
     )}
     ```
  2. Add an explicit tooltip and subtle star icon to disambiguate the metric from query relevance.

---

### Task 1.4 (P1): Per-Card On-Demand Curator Notes (Zero Upfront LLM Cost)
- **Problem**: Generating a mandatory batch pitch for all 5 anime at the top of the page costs ~1,650 tokens on every search and occupies more than 50% of the screen, even if the user never reads it. Merely hiding a pre-generated pitch behind a top toggle would de-clutter the UI, but it would still waste LLM API spend in the background.
- **Implementation**:
  1. **Remove the Mandatory Top Pitch Stream**:
     In `backend/rag_pipeline/orchestrator.py`, bypass the mandatory `synthesizer.generate_pitch_stream` during initial candidate retrieval (saving ~1,650 tokens and $0.0004 per search submission).
  2. **Add Per-Card "Curator Note" Button**:
     In `frontend/src/components/chat/AnimeCard.tsx`, add an interactive button in the card footer next to "More like this":
     `[✨ Curator Note (▾)]` or `[Why this?]`.
  3. **On-Demand Single-Title Synthesis**:
     When the user clicks the button on a specific card, trigger a targeted micro-pitch for that single anime title (or expand cached explanation). This requires only ~80 completion tokens instead of ~350 tokens, paying strictly when engagement occurs. If the user browses without asking for reasons, total LLM rationale cost is strictly $0.

---

### Task 1.5 (P1): Fix Unicode Bullet and Citation Tag Markdown Rendering
- **Problem**: In `frontend/src/components/chat/ConciergePitch.tsx`:
  - Line 216 only checks `line.startsWith('* ')` or `line.startsWith('- ')`. When the LLM outputs unicode bullet characters (`• `), the parser fails to group them as an unordered list (`<ul>`), rendering an unformatted blob.
  - Line 133 regex only matches `[[anime:<id>]]`. If the LLM generates a single bracket `[anime:<id>]`, it renders as raw text.
- **Implementation**:
  1. In `frontend/src/components/chat/ConciergePitch.tsx`, broaden list item detection:
     ```tsx
     const isListItem = (line: string) => /^\s*([*\-•]|\d+\.)\s+/.test(line);
     ```
  2. Broaden citation pattern matching to accept single or double brackets:
     ```tsx
     const tokenPattern = /(\[{1,2}anime:\s*\d+\s*\]{1,2}|\[spoiler redacted\]|\|\|[\s\S]+?\|\||\*\*[^*]+\*\*)/gi;
     ```

---

### Task 1.6 (P1): Soften Negative Constraint Dropouts
- **Problem**: Disliking common genres (such as Action, Horror, Mystery) on a psychological thriller query eliminated 100% of the initial 20 candidates, triggering a jarring "We couldn't find any anime" warning.
- **Implementation**:
  1. Increase the initial retrieval pool before filtering from `top_k=20` to `top_k=50` in `backend/rag_pipeline/orchestrator.py`.
  2. If all candidates are eliminated by negative genre filters, return the closest matches with a soft badge: `"Excluded tag present: [Action]"` rather than returning zero candidates.

---

### Task 1.7 (P2): "Load More" Pagination Button
- **Problem**: Users receive only 5 titles and cannot browse further candidates.
- **Implementation**:
  1. In `frontend/src/routes/ChatPage.tsx`, add a `"Load More Recommendations"` button below the grid.
  2. Pass an `offset` parameter to the backend orchestrator, slicing the next 5 pre-ranked candidates from the existing retrieval session ($0 LLM cost).

---

## 3. Verification & Acceptance Criteria
- [ ] Every anime card displays a valid cover image without `<ImageOff />` placeholder errors.
- [ ] Years and episode counts render as clean integers (`2011`, `26 eps`).
- [ ] Rating badge renders with a star icon (`★ 81%`) and clear tooltip.
- [ ] Anime cards are fully visible above the fold on initial search submission.
- [ ] All citation tags render as clickable interactive chips (`<CitationChip>`).
- [ ] Disliking genres narrows results rather than yielding an empty state.
- [ ] Clicking "Load More" appends the next 5 titles smoothly.
