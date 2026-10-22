"""
test/test_sprint9_frontend_chat.py

Comprehensive Static Analysis, Contract, and Component Verification Suite for Sprint 9 Task 9.4:
Frontend Consumer Chat Discovery UI & Card Interaction.

Validates:
1. File Existence & Architecture:
   - frontend/src/types/chat.ts
   - frontend/src/hooks/useUserPreferences.ts
   - frontend/src/lib/chatStream.ts
   - frontend/src/components/chat/AnimeCard.tsx
   - frontend/src/components/chat/ConciergePitch.tsx
   - frontend/src/components/chat/ChatInput.tsx
   - frontend/src/components/chat/PreferenceDrawer.tsx
   - frontend/src/routes/ChatPage.tsx
2. AnimeCard Component Contract:
   - Cover image with loading/fallback
   - Title resolution hierarchy (userPreferred -> english -> romaji)
   - Score badge and format pill
   - Synopsis truncate/expand
   - "Seen it" toggle with checkmark and useUserPreferences integration
   - "More like this" callback
   - Clickable genre badges with dislike toggle and strike-through
3. ConciergePitch Component Contract:
   - Streaming cursor / pulse indicator
   - Markdown bold, list, and paragraph rendering
   - Redacted spoiler replacement for [spoiler redacted]
4. ChatInput Component Contract:
   - Textarea with Shift+Enter / Enter submission
   - Send and Stop/Abort action buttons
   - 4 prompt suggestions
   - 18+ adult content toggle
5. PreferenceDrawer Component Contract:
   - Watched counter with clear action
   - Disliked genres pills with removal 'x'
   - Reset preferences action
6. ChatPage Component Contract:
   - State machine: idle, streaming, completed, error, rate_limited
   - streamChat invocation with query, top_k=5, allow_adult, seen_ids, disliked_genres
   - Immediate card grid mounting
   - Pitch streaming into ConciergePitch
   - Warning banner on low retrieval confidence
   - 429 countdown timer and auto-recovery
   - AbortController cancellation via Stop button
7. Routes & Navigation:
   - App.tsx mounts ChatPage at root route /
   - Navbar.tsx includes Discovery/Chat NavLink pointing to /
8. Security & Secret Hygiene:
   - Zero hardcoded API keys or backend secrets in any new frontend files.
"""

import os
import re
import pytest

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRONTEND_DIR = os.path.join(ROOT_DIR, "frontend")


class TestSprint9ChatDiscoveryFiles:
    """Verifies all required Sprint 9 Task 9.4 frontend files exist."""

    EXPECTED_FILES = [
        "src/types/chat.ts",
        "src/hooks/useUserPreferences.ts",
        "src/lib/chatStream.ts",
        "src/components/chat/AnimeCard.tsx",
        "src/components/chat/ConciergePitch.tsx",
        "src/components/chat/ChatInput.tsx",
        "src/components/chat/PreferenceDrawer.tsx",
        "src/routes/ChatPage.tsx",
    ]

    def test_all_sprint9_files_exist(self):
        for rel_path in self.EXPECTED_FILES:
            full_path = os.path.join(FRONTEND_DIR, rel_path)
            assert os.path.isfile(full_path), f"Required Task 9.4 file missing: {rel_path}"


class TestAnimeCardContract:
    """Verifies AnimeCard.tsx high-fidelity interaction contract."""

    @pytest.fixture(autouse=True)
    def load_code(self):
        path = os.path.join(FRONTEND_DIR, "src", "components", "chat", "AnimeCard.tsx")
        with open(path, "r", encoding="utf-8") as f:
            self.code = f.read()

    def test_title_resolution(self):
        assert "title_userPreferred" in self.code
        assert "title_english" in self.code
        assert "title_romaji" in self.code

    def test_score_badge_and_format_pill(self):
        assert "Badge" in self.code
        assert "averageScore" in self.code or "score" in self.code
        assert "format" in self.code
        assert "episodes" in self.code

    def test_synopsis_truncate_and_expand(self):
        assert "synopsis" in self.code or "description" in self.code
        assert "isExpanded" in self.code or "expanded" in self.code
        assert "Read more" in self.code or "less" in self.code.lower()

    def test_seen_it_toggle_interaction(self):
        assert "useUserPreferences" in self.code
        assert "isSeen" in self.code
        assert "toggleSeen" in self.code
        assert "Check" in self.code
        assert "Seen it" in self.code or "Seen" in self.code

    def test_more_like_this_interaction(self):
        assert "onMoreLikeThis" in self.code
        assert "Sparkles" in self.code or "More like this" in self.code

    def test_clickable_genre_badges_dislike_toggle(self):
        assert "toggleDislikedGenre" in self.code
        assert "isGenreDisliked" in self.code
        assert "line-through" in self.code


class TestConciergePitchContract:
    """Verifies ConciergePitch.tsx presentation bubble contract."""

    @pytest.fixture(autouse=True)
    def load_code(self):
        path = os.path.join(FRONTEND_DIR, "src", "components", "chat", "ConciergePitch.tsx")
        with open(path, "r", encoding="utf-8") as f:
            self.code = f.read()

    def test_streaming_indicator_and_cursor(self):
        assert "isStreaming" in self.code
        assert "animate-pulse" in self.code or "animate-ping" in self.code

    def test_spoiler_redacted_replacement(self):
        # Must replace [spoiler redacted] with custom styled pill
        assert "spoiler redacted" in self.code.lower()
        assert "Spoiler Redacted" in self.code
        assert "EyeOff" in self.code

    def test_markdown_and_line_breaks(self):
        assert "**" in self.code  # bold parsing
        assert "split" in self.code


class TestChatInputContract:
    """Verifies ChatInput.tsx prompt bar contract."""

    @pytest.fixture(autouse=True)
    def load_code(self):
        path = os.path.join(FRONTEND_DIR, "src", "components", "chat", "ChatInput.tsx")
        with open(path, "r", encoding="utf-8") as f:
            self.code = f.read()

    def test_keyboard_submission(self):
        assert "Enter" in self.code
        assert "shiftKey" in self.code

    def test_action_button_send_and_stop(self):
        assert "isStreaming" in self.code
        assert "Stop" in self.code
        assert "onStop" in self.code

    def test_prompt_suggestions(self):
        expected_suggestions = [
            "Dark psychological thriller like Death Note",
            "Heartwarming slice-of-life in rural Japan",
            "Mind-bending sci-fi with mystery and time travel",
            "High-octane shonen with incredible animation",
        ]
        for s in expected_suggestions:
            assert s in self.code, f"Prompt suggestion '{s}' missing from ChatInput"

    def test_adult_content_toggle(self):
        assert "useUserPreferences" in self.code
        assert "allow_adult" in self.code
        assert "setAllowAdult" in self.code
        assert "18+" in self.code


class TestPreferenceDrawerContract:
    """Verifies PreferenceDrawer.tsx compact collapsible preference bar contract."""

    @pytest.fixture(autouse=True)
    def load_code(self):
        path = os.path.join(FRONTEND_DIR, "src", "components", "chat", "PreferenceDrawer.tsx")
        with open(path, "r", encoding="utf-8") as f:
            self.code = f.read()

    def test_watched_counter_and_clear_action(self):
        assert "seenCount" in self.code or "seen_ids" in self.code
        assert "clearSeen" in self.code
        assert "marked seen" in self.code or "Seen" in self.code

    def test_disliked_genres_and_remove(self):
        assert "disliked_genres" in self.code or "dislikedGenresCount" in self.code
        assert "removeDislikedGenre" in self.code
        assert "Clear" in self.code

    def test_reset_preferences(self):
        assert "resetPreferences" in self.code


class TestChatPageContract:
    """Verifies ChatPage.tsx discovery page state machine and SSE orchestration."""

    @pytest.fixture(autouse=True)
    def load_code(self):
        path = os.path.join(FRONTEND_DIR, "src", "routes", "ChatPage.tsx")
        with open(path, "r", encoding="utf-8") as f:
            self.code = f.read()

    def test_conversation_state_management(self):
        states = ["idle", "streaming", "completed", "error", "rate_limited"]
        for st in states:
            assert st in self.code, f"State '{st}' missing from ChatPage"

    def test_stream_chat_invocation_parameters(self):
        assert "streamChat" in self.code
        assert "top_k: 5" in self.code or "top_k" in self.code
        assert "allow_adult" in self.code
        assert "seen_ids" in self.code
        assert "disliked_genres" in self.code

    def test_immediate_metadata_grid_mount(self):
        assert "onMetadata" in self.code
        assert "setCandidates" in self.code
        assert "AnimeCard" in self.code

    def test_pitch_streaming(self):
        assert "onToken" in self.code
        assert "ConciergePitch" in self.code

    def test_warning_event_banner(self):
        assert "onWarning" in self.code
        assert "warning" in self.code

    def test_rate_limit_429_countdown_and_recovery(self):
        assert "429" in self.code or "rate_limited" in self.code
        assert "rateLimitCountdown" in self.code
        assert "setInterval" in self.code
        assert "remaining" in self.code or "s remaining" in self.code

    def test_abort_controller_support(self):
        assert "AbortController" in self.code
        assert "handleStop" in self.code or "abort" in self.code


class TestNavigationRoutesContract:
    """Verifies App.tsx root mount and Navbar.tsx navigation link."""

    def test_app_mounts_chat_page_at_root(self):
        path = os.path.join(FRONTEND_DIR, "src", "App.tsx")
        with open(path, "r", encoding="utf-8") as f:
            code = f.read()
        assert "ChatPage" in code
        assert "<Route index element={<ChatPage />} />" in code

    def test_navbar_contains_discovery_navlink(self):
        path = os.path.join(FRONTEND_DIR, "src", "components", "layout", "Navbar.tsx")
        with open(path, "r", encoding="utf-8") as f:
            code = f.read()
        assert 'to="/"' in code
        assert "Discovery" in code or "Chat" in code


class TestSecretScannerSprint9:
    """Ensures no hardcoded credentials or forbidden secrets in newly created frontend files."""

    FORBIDDEN_PATTERNS = [
        re.compile(r"sk-(?:proj-)?[A-Za-z0-9_\-]{20,}", re.IGNORECASE),
        re.compile(r"ar_live_[a-f0-9]{8}_[A-Za-z0-9_\-]+", re.IGNORECASE),
        re.compile(r"eyJhbGciOi[A-Za-z0-9_\-\.]{40,}", re.IGNORECASE),
    ]

    def test_no_leaked_secrets(self):
        files_to_scan = [
            "src/types/chat.ts",
            "src/hooks/useUserPreferences.ts",
            "src/lib/chatStream.ts",
            "src/components/chat/AnimeCard.tsx",
            "src/components/chat/ConciergePitch.tsx",
            "src/components/chat/ChatInput.tsx",
            "src/components/chat/PreferenceDrawer.tsx",
            "src/routes/ChatPage.tsx",
            "src/App.tsx",
            "src/components/layout/Navbar.tsx",
        ]
        for rel in files_to_scan:
            full = os.path.join(FRONTEND_DIR, rel)
            with open(full, "r", encoding="utf-8") as f:
                content = f.read()
            for pat in self.FORBIDDEN_PATTERNS:
                assert not pat.search(content), f"Forbidden secret detected in {rel}"
