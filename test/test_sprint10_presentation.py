"""
test/test_sprint10_presentation.py

Automated Static Analysis, Contract, and Presentation Verification Suite for Sprint 10:
Task 10.2: Frontend Citation Highlighting & Card Linking
Task 10.3: Interactive Click-to-Reveal Spoilers

Validates:
1. ConciergePitch.tsx:
   - Structured citation parsing ([[anime:<id>]])
   - Candidate lookup by ID with fallback (Anime #{id})
   - Brand chip presentation with Sparkles icon & hover/click interactivity
   - Interactive click-to-reveal spoilers ([spoiler redacted] and ||content||)
   - Toggle state (EyeOff -> Eye) and safety-scrubbed reveal text
2. AnimeCard.tsx:
   - DOM id="anime-card-{id}" on root card container
   - isHighlighted optional prop
   - Highlight styling ring-2 ring-brand-500 shadow-xl scale-[1.01] transition-all
3. ChatPage.tsx:
   - State highlightedAnimeId
   - handleSelectAnime smooth scrolling and 2.5s auto-clear timeout
   - Proper prop propagation to ConciergePitch and AnimeCard
4. Secret scanning:
   - Zero hardcoded OpenAI or backend credentials
"""

import os
import re
import pytest

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRONTEND_DIR = os.path.join(ROOT_DIR, "frontend")


class TestSprint10PresentationFiles:
    """Verifies that all files updated in Sprint 10 exist."""

    EXPECTED_FILES = [
        "src/components/chat/ConciergePitch.tsx",
        "src/components/chat/AnimeCard.tsx",
        "src/routes/ChatPage.tsx",
    ]

    def test_sprint10_files_exist(self):
        for rel_path in self.EXPECTED_FILES:
            full_path = os.path.join(FRONTEND_DIR, rel_path)
            assert os.path.isfile(full_path), f"Sprint 10 file missing: {rel_path}"


class TestConciergePitchCitationContract:
    """Verifies Task 10.2 Citation chip parsing, candidate lookup, and interactivity in ConciergePitch.tsx."""

    @pytest.fixture(autouse=True)
    def load_code(self):
        path = os.path.join(FRONTEND_DIR, "src", "components", "chat", "ConciergePitch.tsx")
        with open(path, "r", encoding="utf-8") as f:
            self.code = f.read()

    def test_props_contract(self):
        """Verifies ConciergePitchProps accepts text, candidates, onSelectAnime, onHoverAnime."""
        assert "text?:" in self.code or "text:" in self.code
        assert "candidates?:" in self.code or "candidates:" in self.code
        assert "onSelectAnime?:" in self.code or "onSelectAnime:" in self.code
        assert "onHoverAnime?:" in self.code or "onHoverAnime:" in self.code

    def test_structured_citation_pattern(self):
        """Verifies regex pattern for [[anime:<id>]] tags."""
        assert r"\[\[anime:" in self.code or "[[anime:" in self.code
        # Regex or split pattern should capture anime ID
        assert "anime:" in self.code
        assert "CitationChip" in self.code

    def test_citation_chip_candidate_lookup_and_fallback(self):
        """Verifies candidate lookup by id and fallback to Anime #${id}."""
        assert "candidate" in self.code
        assert "Anime #" in self.code
        assert "title_userPreferred" in self.code
        assert "title_english" in self.code

    def test_citation_chip_styling_and_interactivity(self):
        """Verifies brand chip styling, Sparkles icon, and click/hover events."""
        assert "Sparkles" in self.code
        assert "onSelectAnime" in self.code
        assert "onHoverAnime" in self.code
        assert "onMouseEnter" in self.code
        assert "onMouseLeave" in self.code
        assert "bg-brand" in self.code
        assert "cursor-pointer" in self.code

    def test_citation_regex_parsing_logic(self):
        """Validates the python-level regex simulation for [[anime:<id>]] extraction."""
        pitch_sample = (
            "If you love psychological thrillers, check out [[anime:16498]] which keeps you on edge! "
            "Alternatively, [[anime:20]] offers classic ninja adventures."
        )
        pattern = re.compile(r"\[\[anime:\s*(\d+)\s*\]\]", re.IGNORECASE)
        matches = pattern.findall(pitch_sample)
        assert matches == ["16498", "20"]


class TestConciergePitchSpoilerContract:
    """Verifies Task 10.3 Interactive click-to-reveal spoilers in ConciergePitch.tsx."""

    @pytest.fixture(autouse=True)
    def load_code(self):
        path = os.path.join(FRONTEND_DIR, "src", "components", "chat", "ConciergePitch.tsx")
        with open(path, "r", encoding="utf-8") as f:
            self.code = f.read()

    def test_spoiler_patterns_handled(self):
        """Verifies support for both [spoiler redacted] and ||content|| syntax."""
        assert "spoiler redacted" in self.code.lower()
        assert "||" in self.code
        assert "InteractiveSpoiler" in self.code

    def test_spoiler_component_toggle_state(self):
        """Verifies useState toggle behavior for reveal state."""
        assert "isRevealed" in self.code
        assert "setIsRevealed" in self.code or "toggleReveal" in self.code
        assert "useState" in self.code

    def test_spoiler_unrevealed_state_badge(self):
        """Verifies EyeOff icon and click to reveal label in unrevealed state."""
        assert "EyeOff" in self.code
        assert "click to reveal" in self.code.lower()
        assert "blur" in self.code.lower() or "amber" in self.code

    def test_spoiler_revealed_state_transition(self):
        """Verifies Eye icon and revealed message when expanded."""
        assert "Eye" in self.code
        assert "[Spoiler revealed: plot twist redacted for safety]" in self.code
        assert "transition-all" in self.code

    def test_spoiler_regex_parsing_logic(self):
        """Validates python-level regex parsing for scrubbed and piped spoilers."""
        sample = "The protagonist discovers that [spoiler redacted] while ||they are in the matrix||."
        scrubbed_pattern = re.compile(r"\[spoiler redacted\]", re.IGNORECASE)
        piped_pattern = re.compile(r"\|\|([\s\S]+?)\|\|")

        assert scrubbed_pattern.search(sample) is not None
        piped_matches = piped_pattern.findall(sample)
        assert piped_matches == ["they are in the matrix"]


class TestAnimeCardHighlightContract:
    """Verifies Task 10.2 AnimeCard.tsx DOM id anchor and highlight ring styling."""

    @pytest.fixture(autouse=True)
    def load_code(self):
        path = os.path.join(FRONTEND_DIR, "src", "components", "chat", "AnimeCard.tsx")
        with open(path, "r", encoding="utf-8") as f:
            self.code = f.read()

    def test_dom_id_anchor(self):
        """Verifies root container contains id={`anime-card-${anime.id}`}."""
        assert "anime-card-" in self.code
        assert "id=" in self.code

    def test_is_highlighted_prop(self):
        """Verifies AnimeCardProps includes optional isHighlighted boolean."""
        assert "isHighlighted?:" in self.code or "isHighlighted:" in self.code

    def test_highlight_ring_and_glow_styling(self):
        """Verifies highlight ring, glow, and scaling when isHighlighted is true."""
        assert "ring-2" in self.code
        assert "ring-brand-500" in self.code
        assert "shadow-xl" in self.code
        assert "shadow-brand-500/20" in self.code
        assert "scale-[1.01]" in self.code
        assert "transition-all" in self.code
        assert "duration-300" in self.code


class TestChatPageLinkingContract:
    """Verifies Task 10.2 ChatPage.tsx state management, smooth scrolling, and prop wiring."""

    @pytest.fixture(autouse=True)
    def load_code(self):
        path = os.path.join(FRONTEND_DIR, "src", "routes", "ChatPage.tsx")
        with open(path, "r", encoding="utf-8") as f:
            self.code = f.read()

    def test_highlighted_state_management(self):
        """Verifies state highlightedAnimeId initialized in ChatPage."""
        assert "highlightedAnimeId" in self.code
        assert "setHighlightedAnimeId" in self.code

    def test_handle_select_anime_smooth_scroll(self):
        """Verifies handleSelectAnime locates element and calls scrollIntoView with smooth behavior."""
        assert "handleSelectAnime" in self.code
        assert "getElementById" in self.code
        assert "anime-card-" in self.code
        assert "scrollIntoView" in self.code
        assert "behavior: 'smooth'" in self.code or 'behavior: "smooth"' in self.code
        assert "block: 'center'" in self.code or 'block: "center"' in self.code

    def test_auto_clear_highlight_timeout(self):
        """Verifies highlight automatically clears after 2.5 seconds (2500ms)."""
        assert "setTimeout" in self.code
        assert "2500" in self.code

    def test_concierge_pitch_props_passed(self):
        """Verifies candidates, onSelectAnime, and onHoverAnime passed to ConciergePitch."""
        assert "candidates={candidates}" in self.code
        assert "onSelectAnime={handleSelectAnime}" in self.code
        assert "onHoverAnime=" in self.code

    def test_anime_card_highlight_prop_passed(self):
        """Verifies isHighlighted={highlightedAnimeId === anime.id} passed to AnimeCard."""
        assert "isHighlighted={highlightedAnimeId === anime.id}" in self.code


class TestSecretScannerSprint10:
    """Ensures no hardcoded credentials or forbidden secrets in frontend files."""

    FORBIDDEN_PATTERNS = [
        re.compile(r"sk-(?:proj-)?[A-Za-z0-9_\-]{20,}", re.IGNORECASE),
        re.compile(r"ar_live_[a-f0-9]{8}_[A-Za-z0-9_\-]+", re.IGNORECASE),
        re.compile(r"eyJhbGciOi[A-Za-z0-9_\-\.]{40,}", re.IGNORECASE),
    ]

    def test_no_leaked_secrets_in_sprint10(self):
        files_to_scan = [
            "src/components/chat/ConciergePitch.tsx",
            "src/components/chat/AnimeCard.tsx",
            "src/routes/ChatPage.tsx",
        ]
        for rel in files_to_scan:
            full = os.path.join(FRONTEND_DIR, rel)
            with open(full, "r", encoding="utf-8") as f:
                content = f.read()
            for pat in self.FORBIDDEN_PATTERNS:
                assert not pat.search(content), f"Forbidden secret detected in {rel}"
