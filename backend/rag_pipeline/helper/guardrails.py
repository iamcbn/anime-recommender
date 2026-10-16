"""
backend/rag_pipeline/helper/guardrails.py

Sprint 3: Production Domain Guardrails & Active Content Filter
- Task 3.1: Multi-Tier Pre-Retrieval Validation (<15ms, zero false-positives on real anime titles)
- Task 3.1: Cross-Encoder Retrieval Confidence Assessment (threshold < -6.5 fallback)
- Task 3.1: Active Post-Synthesis Spoiler Scrubber (redacting twists & reveals)
"""

import re
import html
from typing import Any, List, Dict, Optional, Tuple, Union
import logging

logger = logging.getLogger(__name__)


# =============================================================================
# COMPILED REGEX PATTERNS: PROMPT INJECTIONS & JAILBREAKS (TIER 1 - UNCONDITIONAL)
# =============================================================================

PROMPT_INJECTION_PATTERNS = re.compile(
    r"(?:"
    # Instruction Overrides & Reset Commands
    r"\b(?:ignore|disregard|forget|override|bypass|clear|drop)\s+(?:all\s+)?(?:previous|prior|above|system|existing)?\s*(?:instructions|prompts|rules|directives|constraints|guidelines)\b"
    r"|\bfrom\s+now\s+on\b.*?\b(?:you\s+must|you\s+are|you\s+will|act\s+as|pretend\s+to\s+be)\b"
    r"|\b(?:do\s+not|never)\s+follow\s+(?:the\s+)?(?:system|above|previous)\s+instructions\b"
    # System Prompt Leak / Extraction Attempts
    r"|\b(?:repeat|print|reveal|show|display|output|leak|dump|give\s+me)\s+(?:the\s+|your\s+)?(?:system\s+prompt|initial\s+prompt|hidden\s+prompt|developer\s+prompt|system\s+instructions|initial\s+instructions|base\s+instructions|system\s+message|rules\s+above)\b"
    r"|\bwhat\s+(?:is|are)\s+(?:the\s+|your\s+)?(?:system\s+prompt|initial\s+instructions|hidden\s+rules|system\s+instructions)\b"
    r"|\boutput\s+everything\s+(?:above|before\s+this)\b"
    # Jailbreaks & Uncensored Mode Swings
    r"|\b(?:dan\s+mode|do\s+anything\s+now)\b"
    r"|\bdeveloper\s+mode\s+(?:is\s+)?(?:enabled|on|active|activated)\b"
    r"|\b(?:jailbreak|jailbroken)\b"
    r"|\b(?:unrestricted|uncensored|unfiltered)\s+(?:mode|model|ai|assistant|persona)\b"
    r"|\bpretend\s+(?:you\s+have\s+no\s+(?:rules|filters|limits|constraints)|there\s+are\s+no\s+rules)\b"
    r"|\b(?:bypass|disable)\s+(?:the\s+)?(?:safety|content|ethical)\s+(?:filter|filters|guardrails)\b"
    r"|\b(?:sudo\s+mode|god\s+mode)\b"
    # Template Injection & Delimiter Manipulation
    r"|<\|im_start\|>|<\|im_end\|>|<\|system\|>|<\|user\|>|<\|assistant\|>"
    r"|\[INST\]|\[/INST\]|<<SYS>>|</<SYS>>"
    r"|```(?:system|assistant|human)"
    r"|###\s*(?:System|Instruction|Assistant|Human):"
    r")",
    re.IGNORECASE | re.DOTALL
)


# =============================================================================
# COMPILED REGEX PATTERNS: OUT-OF-SCOPE TASKS (TIER 2 - CONDITIONAL WITH WHITELIST)
# =============================================================================

# 1. Imperative Coding / Programming Tasks
OOS_CODING_PATTERNS = re.compile(
    r"(?:"
    r"\b(?:write|fix|debug|refactor|compile|run|implement|optimize)\s+(?:a\s+|the\s+|my\s+|this\s+)?(?:python|javascript|typescript|c\+\+|cpp|c#|java|rust|go|bash|powershell|sql|html|css|php|ruby|swift|kotlin)\s+(?:code|script|program|function|class|algorithm|regex|query)\b"
    r"|\b(?:write|give\s+me)\s+(?:a\s+)?(?:python|javascript|typescript|c\+\+|cpp|c#|java|rust|go|bash|sql)\s+(?:script|program|function|snippet|app)\b"
    r"|\bhow\s+to\s+(?:code|program|implement)\s+.*?\s+in\s+(?:python|javascript|typescript|c\+\+|cpp|c#|java|rust|go|sql)(?:\b|(?<=\+)|(?<=#))"
    r"|\b(?:fix|debug)\s+(?:this\s+|my\s+)?(?:code|bug|error|exception|syntax\s+error|stack\s*trace)\b"
    r"|\b(?:def|class)\s+[a-zA-Z_][a-zA-Z0-9_]*\s*\(.*?\)\s*:"
    r"|\b(?:public\s+static\s+void\s+main|console\.log\(|import\s+[a-zA-Z0-9_]+\s+as\s+)"
    r"|\bhow\s+to\s+(?:hack|exploit|penetrate|crack)\s+(?:wifi|password|database|server|website)\b"
    r")",
    re.IGNORECASE
)

# 2. Math Calculations & Equations
OOS_MATH_PATTERNS = re.compile(
    r"(?:"
    r"\b(?:solve|calculate|evaluate|compute)\s+(?:the\s+)?(?:equation|math\s+problem|system\s+of\s+equations|integral|derivative|limit|matrix|eigenvalue)\b"
    r"|\b(?:solve|calculate|compute|evaluate|what\s+is)\s+[-+]?\d+(?:\.\d+)?\s*[\+\-\*\/\^%]\s*[-+]?\d+(?:\.\d+)?\b"
    r"|\bwhat\s+is\s+(?:\d{1,8}\s*[\+\-\*\/\^%]\s*\d{1,8})\b"
    r"|^\s*(?:solve:?\s*)?[-+]?[0-9a-zA-Z\(\)\.\s\+\-\*\/\^]{2,}\s*=\s*[-+]?[0-9a-zA-Z\(\)\.\s\+\-\*\/\^]{1,}\s*$"
    r")",
    re.IGNORECASE
)

# 3. Real-world Politics & Geopolitics
OOS_POLITICS_PATTERNS = re.compile(
    r"(?:"
    r"\b(?:who\s+is|who's|list\s+of)\s+(?:the\s+)?(?:current\s+|former\s+)?(?:president|prime\s+minister|vice\s+president|chancellor|monarch|governor|senator)\s+of\s+(?!(?:the\s+)?(?:student\s+council|anime|manga|club)\b)[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?\b"
    r"|\bwho\s+won\s+the\s+(?:presidential\s+|general\s+|senate\s+)?election\b"
    r"|\bwhat\s+is\s+the\s+capital\s+of\s+[A-Z][a-z]+\b"
    r"|\b(?:gdp|inflation\s+rate|unemployment\s+rate)\s+of\s+[A-Z][a-z]+\b"
    r")",
    re.IGNORECASE
)

# 4. Finance, Stock Trading & Cryptocurrency
OOS_FINANCE_PATTERNS = re.compile(
    r"(?:"
    r"\b(?:stock\s+price\s+of|ticker\s+symbol\s+for|nasdaq\s+index|s&p\s*500)\b"
    r"|\b(?:buy|sell|trade|invest\s+in|mining|staking)\s+(?:crypto|cryptocurrency|bitcoin|btc|ethereum|eth|solana|dogecoin|memecoin|nft)\b"
    r"|\b(?:crypto|bitcoin|ethereum)\s+(?:price|ticker|prediction|portfolio|trading|exchange|wallet)\b"
    r")",
    re.IGNORECASE
)

# 5. Live Weather, Cooking Recipes, Medical Advice
OOS_GENERAL_PATTERNS = re.compile(
    r"(?:"
    r"\b(?:what(?:'s|\s+is)\s+the\s+weather|weather\s+forecast\s+(?:for|in)|current\s+temperature\s+in)\s+[a-zA-Z\s]{2,}\b"
    r"|\b(?:recipe|cooking\s+instructions)\s+for\s+[a-zA-Z\s]{3,}\b"
    r"|\b(?:diagnose\s+my|medical\s+advice\s+for|symptoms\s+of)\s+[a-zA-Z\s]{3,}\b"
    r")",
    re.IGNORECASE
)


# =============================================================================
# COMPILED REGEX PATTERNS: PROTECTED ANIME ENTITIES & NARRATIVE CUES
# =============================================================================

# Real anime titles and tokens that could otherwise collide with OOS filters
PROTECTED_ANIME_ENTITIES = re.compile(
    r"(?:"
    r"\bCode\s+Geass(?:\s*:\s*Lelouch\s+of\s+the\s+Rebellion)?\b"
    r"|\bSteins\s*;\s*Gate(?:\s*0)?\b"
    r"|\bGhost\s+in\s+the\s+Shell(?:\s*:\s*Stand\s+Alone\s+Complex)?\b"
    r"|\bErased\b"
    r"|\bMonster\b"
    r"|\bDeath\s+Note\b"
    r"|\bPsycho\s*-\s*Pass\b"
    r"|\bSerial\s+Experiments\s+Lain\b"
    r"|\bNew\s+Game!\b"
    r"|\bBattle\s+Programmer\s+Shirase\b"
    r"|\bSummer\s+Wars\b"
    r"|\bWeathering\s+[Ww]ith\s+You\b"
    r"|\bDaily\s+Lives\s+of\s+High\s+School\s+Boys\b"
    r"|\bKaguya\s*-\s*sama(?:\s*:\s*Love\s+Is\s+War)?\b"
    r"|\bstudent\s+council\s+president\b"
    r"|\bclass\s+president\b"
    r"|\bKaichou\s+wa\s+Maid\s*-\s*sama!\b"
    r")",
    re.IGNORECASE
)

# Generic anime/manga narrative context cues
ANIME_CONTEXT_CUES = re.compile(
    r"\b(?:"
    r"anime|manga|light\s+novel|ova|ona|series|show|shows|animation|animated|"
    r"isekai|shounen|shonen|seinen|shojo|shoujo|josei|mecha|slice\s+of\s+life|"
    r"waifu|husbando|otaku|protagonist|antagonist|villain|character|characters|"
    r"episode|episodes|season|seasons|recommend|recommendation|recommendations|"
    r"similar\s+to|like|watch|watching|synopsis|studio|voice\s+actor|"
    r"familiars|familiar|snake|snakes|cyberpunk|hacker|hackers"
    r")\b",
    re.IGNORECASE
)


# =============================================================================
# COMPILED REGEX PATTERNS: SPOILER SCRUBBER
# =============================================================================

# Narrative plot twist reveals, unmasking of masterminds/killers, climax deaths
SPOILER_PATTERNS = re.compile(
    r"(?:"
    # Climax / Ending character deaths: "dies in the end", "is killed at the climax"
    r"\b(?:dies?|died|is\s+killed|was\s+killed|will\s+die|ends\s+up\s+dying|meets\s+(?:their|his|her)\s+end|sacrifices\s+(?:themselves|himself|herself))\s+(?:at|in|near)\s+the\s+(?:end|finale|climax|last\s+episode|last\s+chapter)\b"
    r"|\b(?:at|in)\s+the\s+(?:end|finale|climax|last\s+episode),\s*(?:[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?|\bthe\s+protagonist\b|\bthe\s+hero\b|\bthe\s+main\s+character\b)\s+(?:dies|is\s+killed)\b"
    r"|\b(?:kills?|murders?)\s+[A-Za-z0-9_\'\s]{1,25}?\s+(?:at|in|near)\s+the\s+(?:end|finale|climax)\b"
    # Unmasking of killer/villain: "is actually the murderer", "revealed to be the villain"
    r"|\b(?:is|was|turns\s+out\s+to\s+be|revealed\s+to\s+be|revealed\s+as|discovered\s+to\s+be)\s+(?:actually\s+|secretly\s+)?(?:the\s+)?(?:real\s+|actual\s+|true\s+)?(?:killer|murderer|villain|culprit|mastermind|traitor|final\s+boss)\b"
    r"|\b(?:the\s+)?(?:real\s+|actual\s+|true\s+)?(?:killer|murderer|culprit|mastermind|traitor)\s+(?:is|was)\s+(?:revealed\s+to\s+be\s+)?(?!(?:still|on\s+the\s+loose|unknown|at\s+large|hunting|lurking|a\s+serial|a\s+young|not|never|someone|everywhere)\b)[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?\b"
    # True identity reveals: "true identity is revealed as", "secret identity is"
    r"|\b(?:true|real|secret|hidden)\s+identity\s+(?:is|was|revealed\s+to\s+be|revealed\s+as)\s+[A-Za-z0-9_\'\s]{1,30}?\b"
    r"|\b(?:is|was)\s+(?:actually|secretly|revealed\s+to\s+be)\s+(?:the\s+)?(?:same\s+person\s+as|alive\s+all\s+along|the\s+main\s+villain|the\s+mastermind)\b"
    r"|\b(?:ending\s+twist|climax\s+twist|plot\s+twist)\s+(?:is|reveals)\s+that\b"
    # Markup and explicit spoiler wrappers: ||spoiler||, [spoiler]...[/spoiler], <spoiler>...</spoiler>
    r"|\|\|[\s\S]*?\|\|"
    r"|\[spoiler\][\s\S]*?\[/spoiler\]"
    r"|<\s*spoiler\s*>[\s\S]*?<\s*/\s*spoiler\s*>"
    r")",
    re.IGNORECASE
)


# =============================================================================
# DATA STRUCTURES
# =============================================================================

class GuardrailResult:
    """
    Structured outcome of pre-retrieval intent and injection validation.

    Supports both tuple-like unpacking:
        valid, msg = DomainGuardrails.validate_intent(query)
    And direct property access:
        result.is_valid
        result.detail
        result.category
    """
    def __init__(
        self,
        is_valid: bool,
        detail: str = "",
        category: str = "ok"
    ):
        self.is_valid = is_valid
        self.detail = detail
        self.category = category

    def __iter__(self):
        # Enables unpacking as (is_valid, detail)
        return iter((self.is_valid, self.detail))

    def __getitem__(self, index: int):
        return (self.is_valid, self.detail)[index]

    def __bool__(self) -> bool:
        return self.is_valid

    def __repr__(self) -> str:
        return (
            f"GuardrailResult(is_valid={self.is_valid}, "
            f"category={self.category!r}, "
            f"detail={self.detail!r})"
        )


class ConfidenceAssessment:
    """
    Structured outcome of Cross-Encoder retrieval confidence assessment.
    
    Supports both tuple-like unpacking:
        is_confident, fallback_message = DomainGuardrails.check_retrieval_confidence(results)
    And direct property access:
        assessment.is_confident
        assessment.max_score
        assessment.fallback_message
    """
    def __init__(
        self,
        is_confident: bool,
        fallback_message: str,
        max_score: Optional[float] = None
    ):
        self.is_confident = is_confident
        self.fallback_message = fallback_message
        self.max_score = max_score

    def __iter__(self):
        # Enables unpacking as (is_confident, fallback_message)
        return iter((self.is_confident, self.fallback_message))

    def __getitem__(self, index: int):
        return (self.is_confident, self.fallback_message)[index]

    def __bool__(self) -> bool:
        return self.is_confident

    def __repr__(self) -> str:
        return (
            f"ConfidenceAssessment(is_confident={self.is_confident}, "
            f"max_score={self.max_score}, "
            f"fallback_message={self.fallback_message!r})"
        )


# =============================================================================
# DOMAIN GUARDRAILS ENGINE
# =============================================================================

class DomainGuardrails:
    """
    Comprehensive Guardrails Engine for Conversational Anime RAG:
    1. Pre-Retrieval Intent & Scope Validation (<15ms, zero false positives on anime titles).
    2. Retrieval Cross-Encoder Confidence Evaluation (Threshold < -6.5 fallback trigger).
    3. Active Post-Synthesis Spoiler Scrubber (redacting plot twists and climax reveals).
    """

    MIN_CONFIDENCE: float = -6.5
    MAX_QUERY_LENGTH: int = 1500

    # Fallback recommendations for low-confidence or downstream outage scenarios
    CANONICAL_FALLBACKS: List[Dict[str, Any]] = [
        {
            "id": 5114,
            "title_romaji": "Fullmetal Alchemist: Brotherhood",
            "title_english": "Fullmetal Alchemist: Brotherhood",
            "genres": ["Action", "Adventure", "Drama", "Fantasy"],
            "averageScore": 91,
            "seasonYear": 2009,
            "synopsis": "Two brothers search for a Philosopher's Stone to restore their bodies after a disastrous alchemy experiment.",
        },
        {
            "id": 9253,
            "title_romaji": "Steins;Gate",
            "title_english": "Steins;Gate",
            "genres": ["Drama", "Sci-Fi", "Suspense"],
            "averageScore": 90,
            "seasonYear": 2011,
            "synopsis": "A self-proclaimed mad scientist invents a microwave that sends text messages into the past, triggering unforeseen consequences.",
        },
        {
            "id": 1535,
            "title_romaji": "Death Note",
            "title_english": "Death Note",
            "genres": ["Mystery", "Psychological", "Supernatural", "Thriller"],
            "averageScore": 84,
            "seasonYear": 2006,
            "synopsis": "A high school prodigy discovers a supernatural notebook granting him the power to kill anyone whose name and face he knows.",
        },
        {
            "id": 1575,
            "title_romaji": "Code Geass: Hangyaku no Lelouch",
            "title_english": "Code Geass: Lelouch of the Rebellion",
            "genres": ["Action", "Drama", "Mecha", "Sci-Fi"],
            "averageScore": 85,
            "seasonYear": 2006,
            "synopsis": "An exiled prince gains the power of absolute obedience and leads a rebellion against the tyrannical Holy Britannian Empire.",
        },
        {
            "id": 19,
            "title_romaji": "Monster",
            "title_english": "Monster",
            "genres": ["Drama", "Mystery", "Psychological", "Thriller"],
            "averageScore": 88,
            "seasonYear": 2004,
            "synopsis": "A brilliant Japanese neurosurgeon in Germany risks everything to track down a sociopathic former patient he saved years prior.",
        },
    ]

    # -------------------------------------------------------------------------
    # 1. PRE-RETRIEVAL VALIDATION
    # -------------------------------------------------------------------------

    @classmethod
    def validate_intent(cls, query: str) -> GuardrailResult:
        """
        Validates user query before search/retrieval execution.
        Executes in < 15ms (AC 3.2).

        Returns:
            GuardrailResult: can be unpacked as (is_valid, detail)
                             or accessed via .is_valid, .detail, .category.
        """
        if not query or not query.strip():
            return GuardrailResult(
                is_valid=False,
                detail="Query cannot be empty. Please ask for an anime recommendation, title, or genre!",
                category="empty_query"
            )

        cleaned_query = query.strip()

        # Length validation
        if len(cleaned_query) > cls.MAX_QUERY_LENGTH:
            return GuardrailResult(
                is_valid=False,
                detail=(
                    f"Query exceeds maximum allowed length of {cls.MAX_QUERY_LENGTH} characters. "
                    "Please provide a concise recommendation request."
                ),
                category="query_too_long"
            )

        # ---------------------------------------------------------------------
        # TIER 1: Prompt Injections & Jailbreaks (Unconditional Rejection)
        # ---------------------------------------------------------------------
        if PROMPT_INJECTION_PATTERNS.search(cleaned_query):
            logger.warning(f"[Guardrails] Prompt injection detected in query: {cleaned_query[:80]}...")
            return GuardrailResult(
                is_valid=False,
                detail=(
                    "Your request contains instructions that override system behavior or violate safety policies. "
                    "I specialize strictly in anime recommendations!"
                ),
                category="prompt_injection"
            )

        # ---------------------------------------------------------------------
        # TIER 2: Out-Of-Scope Checks with Anime Whitelist & Context Protection
        # ---------------------------------------------------------------------
        # Check if the query explicitly features protected anime titles
        has_protected_title = bool(PROTECTED_ANIME_ENTITIES.search(cleaned_query))
        has_anime_cues = bool(ANIME_CONTEXT_CUES.search(cleaned_query))

        # Check Coding / Software Engineering
        if OOS_CODING_PATTERNS.search(cleaned_query):
            # Only allow if explicitly framed as anime narrative/title
            # e.g. "anime about coding" or "anime with python familiars", but reject "write a python script"
            is_coding_request = bool(
                re.search(
                    r"\b(?:write|debug|fix|run|compile|implement)\s+(?:a\s+|the\s+|my\s+)?(?:python|code|script|function|program)\b",
                    cleaned_query,
                    re.IGNORECASE
                )
            )
            if is_coding_request:
                return GuardrailResult(
                    is_valid=False,
                    detail=(
                        "I specialize strictly in anime recommendations and narratives, not code execution or programming. "
                        "Feel free to ask for anime about programmers, hackers, or virtual reality!"
                    ),
                    category="out_of_scope_coding"
                )
            if not (has_protected_title or has_anime_cues):
                return GuardrailResult(
                    is_valid=False,
                    detail=(
                        "I specialize strictly in anime recommendations and narratives. "
                        "Please ask an anime or narrative query!"
                    ),
                    category="out_of_scope_coding"
                )

        # Check Math Equations
        if OOS_MATH_PATTERNS.search(cleaned_query):
            if not (has_protected_title or has_anime_cues):
                return GuardrailResult(
                    is_valid=False,
                    detail=(
                        "I specialize strictly in anime recommendations and narratives, not solving math problems. "
                        "Feel free to ask for anime featuring intellectual battles, mind games, or strategic geniuses!"
                    ),
                    category="out_of_scope_math"
                )

        # Check Real-World Politics & Current Affairs
        if OOS_POLITICS_PATTERNS.search(cleaned_query):
            if not has_protected_title:
                return GuardrailResult(
                    is_valid=False,
                    detail=(
                        "I specialize strictly in anime recommendations. "
                        "I do not answer questions about real-world political figures or current geopolitical affairs."
                    ),
                    category="out_of_scope_politics"
                )

        # Check Cryptocurrency & Stock Trading
        if OOS_FINANCE_PATTERNS.search(cleaned_query):
            if not (has_protected_title or has_anime_cues):
                return GuardrailResult(
                    is_valid=False,
                    detail=(
                        "I specialize strictly in anime recommendations. "
                        "I do not provide financial advice, stock quotes, or cryptocurrency information."
                    ),
                    category="out_of_scope_finance"
                )

        # Check Live Weather, Recipes, Medical Diagnosis
        if OOS_GENERAL_PATTERNS.search(cleaned_query):
            if not (has_protected_title or has_anime_cues):
                return GuardrailResult(
                    is_valid=False,
                    detail=(
                        "I specialize strictly in anime recommendations and narrative discovery. "
                        "Please ask an anime, manga, or story-related question!"
                    ),
                    category="out_of_scope_general"
                )

        return GuardrailResult(is_valid=True, detail="", category="ok")

    @classmethod
    def is_valid_query(cls, query: str) -> bool:
        """Convenience boolean helper for intent validity."""
        return cls.validate_intent(query).is_valid

    # -------------------------------------------------------------------------
    # 2. RETRIEVAL CONFIDENCE ASSESSMENT
    # -------------------------------------------------------------------------

    @classmethod
    def get_max_rerank_score(cls, results: Any) -> Optional[float]:
        """
        Extracts the highest Cross-Encoder rerank score from candidate results.
        Supports list of dicts, pandas DataFrame, or list of numeric scores.
        """
        if results is None:
            return None
        if hasattr(results, "empty") and results.empty:
            return None
        if isinstance(results, (list, tuple)) and len(results) == 0:
            return None

        # Handle list of candidate dictionaries or float scores
        if isinstance(results, list):
            scores = []
            for item in results:
                if isinstance(item, dict):
                    score = item.get("cross_encoder_score")
                    if score is not None:
                        try:
                            scores.append(float(score))
                        except (ValueError, TypeError):
                            pass
                elif isinstance(item, (int, float)):
                    scores.append(float(item))
            return max(scores) if scores else None

        # Handle pandas DataFrame
        if hasattr(results, "empty") and not results.empty:
            if "cross_encoder_score" in results.columns:
                series = results["cross_encoder_score"].dropna()
                return float(series.max()) if not series.empty else None

        return None

    @classmethod
    def check_retrieval_confidence(
        cls,
        results: Any,
        threshold: Optional[float] = None
    ) -> ConfidenceAssessment:
        """
        Checks Cross-Encoder rerank scores against the minimum confidence threshold.
        If max rerank score is < -6.5 (or results are empty), triggers graceful fallback.

        Args:
            results: List of candidate dicts or DataFrame containing 'cross_encoder_score'.
            threshold: Minimum acceptable cross-encoder score (default: -6.5).

        Returns:
            ConfidenceAssessment: can be unpacked as (is_confident, fallback_message)
                                  or inspected via .is_confident and .max_score.
        """
        min_threshold = threshold if threshold is not None else cls.MIN_CONFIDENCE
        max_score = cls.get_max_rerank_score(results)

        is_empty = False
        if results is None:
            is_empty = True
        elif hasattr(results, "empty"):
            is_empty = bool(results.empty)
        elif isinstance(results, (list, tuple)):
            is_empty = (len(results) == 0)

        # Case 1: Empty results
        if is_empty or max_score is None:
            return ConfidenceAssessment(
                is_confident=False,
                max_score=None,
                fallback_message=(
                    "We couldn't find any anime matching your query. "
                    "Try broadening your terms, specifying genres (e.g. 'cyberpunk sci-fi', 'slice-of-life comedy'), "
                    "or mentioning titles you've enjoyed."
                )
            )

        # Case 2: Max score below minimum confidence threshold
        if max_score < min_threshold:
            logger.info(
                f"[Guardrails] Low retrieval confidence detected: max_score={max_score:.2f} < threshold={min_threshold:.2f}"
            )
            return ConfidenceAssessment(
                is_confident=False,
                max_score=max_score,
                fallback_message=(
                    f"Our database returned low confidence matches (relevance score: {max_score:.2f}). "
                    "Try refining your prompt with specific genres, themes, character types, "
                    "or similar anime titles for sharper recommendations!"
                )
            )

        # Case 3: Confident results
        return ConfidenceAssessment(
            is_confident=True,
            max_score=max_score,
            fallback_message=""
        )

    @classmethod
    def get_fallback_recommendations(cls) -> List[Dict[str, Any]]:
        """Returns canonical high-reputation fallback anime candidates."""
        return list(cls.CANONICAL_FALLBACKS)

    # -------------------------------------------------------------------------
    # 3. ACTIVE POST-SYNTHESIS SPOILER SCRUBBER
    # -------------------------------------------------------------------------

    @classmethod
    def scrub_spoilers(cls, text: str, placeholder: str = "[spoiler redacted]") -> str:
        """
        Active post-synthesis spoiler scrubber.
        Filters reveals (climax deaths, twist culprits, secret identities, explicit spoiler tags)
        while preserving natural anime phrasing, synopses, and markdown formatting.

        Args:
            text: The generated conversational pitch or candidate synopsis.
            placeholder: The redacted replacement token (default: '[spoiler redacted]').

        Returns:
            Scrubbed text with spoilers sanitized.
        """
        if not text:
            return text

        return SPOILER_PATTERNS.sub(placeholder, text)

    @classmethod
    def scrub_stream_chunk(
        cls,
        chunk: str,
        buffer: str = "",
        placeholder: str = "[spoiler redacted]"
    ) -> Tuple[str, str]:
        """
        Streaming-aware spoiler scrubber for Server-Sent Events (SSE) token chunks.
        Buffers partial trailing words to prevent multi-token spoiler reveals from
        slipping past chunk boundaries.

        Returns:
            Tuple of (emittable_safe_text, new_buffer).
        """
        combined = buffer + chunk
        # If combined text contains potential boundary spoiler fragment, buffer last 30 chars
        if len(combined) <= 40:
            scrubbed = cls.scrub_spoilers(combined, placeholder=placeholder)
            return "", scrubbed

        # Process everything up to the last word boundary
        last_space = combined.rfind(" ")
        if last_space == -1 or last_space < 30:
            split_idx = max(0, len(combined) - 30)
        else:
            split_idx = last_space

        head = combined[:split_idx]
        tail = combined[split_idx:]

        scrubbed_head = cls.scrub_spoilers(head, placeholder=placeholder)
        return scrubbed_head, tail
