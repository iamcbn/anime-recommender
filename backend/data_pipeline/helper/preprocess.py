# backend\data_pipeline\helper\preprocess.py script

import pandas as pd
import json
import html
from pathlib import Path
import re



class Preprocessor:
    DATA_FILE = "anilist_anime_data_complete.xlsx"

    # Relationship groups
    KEEP_RELATIONS = {"SEQUEL", "PREQUEL", "SPIN_OFF", "SIDE_STORY"}
    IGNORE_RELATIONS = {
        "ADAPTATION", "ALTERNATIVE", "CHARACTER",
        "PARENT", "OTHER", "SUMMARY"
    }

    def __init__(self, data_dir: str, state_version):
        self.data_dir = Path(data_dir).resolve()
        self.state_version = state_version

        self.data_file = (
            self.data_dir
            / f"v{self.state_version}"
            / "raw_data"
            / self.DATA_FILE
        )

        self.raw_data = pd.read_excel(self.data_file)

    # ----------------------------
    # CLEANING HELPERS
    # ----------------------------

    @staticmethod
    def clean_description(text):
        if pd.isna(text):
            return None

        # Decode HTML entities
        text = html.unescape(text)

        # Remove HTML tags
        text = re.sub(r"<.*?>", " ", text)

        # Normalise whitespace
        text = re.sub(r"\s+", " ", text)

        # Fix escaped backslashes
        text = text.replace("\\'", "'").replace('\\"', '"')
        text = re.sub('\"\"', '"', text)



        return text.strip()


    @staticmethod
    def extract_relation_types(relations):
        """
        Safely extract relationship types from relations column
        """
        if pd.isna(relations):
            return set()

        try:
            if isinstance(relations, str):
                relations = json.loads(relations)
        except Exception:
            return set()

        rel_types = set()
        for r in relations:
            rel_type = r.get("relationType")
            if rel_type:
                rel_types.add(rel_type.upper())

        return rel_types

    def should_keep_entry(self, relations):
        """
        Decide whether this anime should remain in v1 catalogue
        """
        rel_types = self.extract_relation_types(relations)

        # No relations at all → keep
        if not rel_types:
            return True

        # Has at least one meaningful relationship → keep
        if rel_types & self.KEEP_RELATIONS:
            return True

        # Only ignorable relationships → drop
        return False

    def classify_relationship(self, relations):
        """
        Classify anime using only meaningful relationship types
        """
        rel_types = self.extract_relation_types(relations)

        if "SEQUEL" in rel_types:
            return "sequel"
        if "PREQUEL" in rel_types:
            return "prequel"
        if "SPIN_OFF" in rel_types:
            return "spin_off"
        if "SIDE_STORY" in rel_types:
            return "side_story"

        return "original"

    @staticmethod
    def parse_json(x):
        """
        Parse stringified JSON into Python objects.
        Always returns a list (empty if missing or invalid).
        """
        import ast

        if isinstance(x, list):
            return x
        if isinstance(x, dict):
            return [x]
        if pd.isna(x):
            return []
        if isinstance(x, str):
            try:
                parsed = json.loads(x)
                if isinstance(parsed, list):
                    return parsed
                if isinstance(parsed, dict):
                    return [parsed]
            except Exception:
                try:
                    # Fallback for Python stringified lists (e.g. "['Action', 'Comedy']")
                    parsed = ast.literal_eval(x)
                    if isinstance(parsed, list):
                        return parsed
                    if isinstance(parsed, dict):
                        return [parsed]
                except Exception:
                    return []
        return []


    @staticmethod
    def build_name_set(row, cols=["title_english", "title_romaji", "title_userPreferred"]):
        names = []

        for col in cols:
            val = row.get(col)
            if isinstance(val, str) and val.strip():
                names.append(val.strip())

        for syn in row.get("synonyms", []):
            if isinstance(syn, str) and syn.strip():
                names.append(syn.strip())

        # Deduplicate case-insensitively, preserve order
        seen = set()
        cleaned = []
        for n in names:
            key = n.lower()
            if key not in seen:
                seen.add(key)
                cleaned.append(n)

        return cleaned

    @staticmethod
    def build_embedding_text(row):
        parts = []

        # Description FIRST — anchors SBERT in semantic/description space.
        # Putting metadata before the description skews the embedding toward
        # structured tokens (Format:, Year:, Studios:) and away from the
        # semantic content that user queries are written against.
        if isinstance(row.get("description"), str):
            parts.append(row["description"])

        # Title aliases next — strong signal for exact-match queries
        if row.get("name_text"):
            parts.append(row["name_text"])

        # Structured metadata
        if pd.notna(row.get("format")) and str(row.get("format")).strip():
            parts.append(f"Format: {row['format']}")
            
        if pd.notna(row.get("seasonYear")):
            try:
                parts.append(f"Year: {int(row['seasonYear'])}")
            except (ValueError, TypeError):
                pass
                
        if pd.notna(row.get("source")) and str(row.get("source")).strip():
            parts.append(f"Source: {row['source']}")
            
        if pd.notna(row.get("countryOfOrigin")) and str(row.get("countryOfOrigin")).strip():
            parts.append(f"Country: {row['countryOfOrigin']}")
            
        studios = Preprocessor.parse_json(row.get("studios"))
        if studios:
            studio_names = []
            for s in studios:
                node = s.get("node", {})
                if node.get("isAnimationStudio") and node.get("name"):
                    studio_names.append(node["name"])
            if studio_names:
                parts.append("Studios: " + ", ".join(studio_names))

        if isinstance(row.get("genres"), list) and row["genres"]:
            parts.append("Genres: " + ", ".join(row["genres"]))

        # Top tags sorted by AniList rank (most relevant first), capped at 15,
        # spoiler and adult tags excluded.
        tag_names = Preprocessor.extract_tags(row.get("tags"), top_n=15)
        if tag_names:
            parts.append("Tags: " + ", ".join(tag_names))

        # Main characters (MAIN role only, up to 8 names)
        char_names = Preprocessor.extract_main_characters(row.get("characters"), top_n=8)
        if char_names:
            parts.append("Main Characters: " + ", ".join(char_names))

        # Key creative staff: Director, Original Creator, Series Composition
        staff_entries = Preprocessor.extract_key_staff(row.get("staff"))
        if staff_entries:
            parts.append("Staff: " + ", ".join(staff_entries))

        final_text = " ".join(parts)
        # FastText strictly rejects newlines, so we must purge any that slipped through
        return final_text.replace("\n", " ").replace("\r", "")

    # ----------------------------
    # FIELD EXTRACTORS
    # ----------------------------

    @staticmethod
    def extract_tags(tags, top_n: int = 15):
        """
        Extract tag names sorted by AniList rank (descending), capped at top_n.
        Spoiler and adult tags are included as per user request.
        """
        try:
            if isinstance(tags, str):
                tags = json.loads(tags)
        except Exception:
            return []

        if not isinstance(tags, list):
            return []

        # Keep all valid dictionary tags
        filtered = [t for t in tags if isinstance(t, dict)]

        # Sort by rank descending (higher rank = more relevant to this anime)
        filtered.sort(key=lambda x: x.get("rank", 0), reverse=True)

        return [t["name"] for t in filtered[:top_n] if t.get("name")]

    @staticmethod
    def extract_main_characters(characters, top_n: int = 8):
        """
        Extract the names of MAIN role characters.
        Handles both flat structures (name at edge level) and nested node
        structures (name inside node.name.full) as used by the AniList API.
        """
        try:
            if isinstance(characters, str):
                characters = json.loads(characters)
        except Exception:
            return []

        if not isinstance(characters, list):
            return []

        names = []
        for char in characters:
            if not isinstance(char, dict):
                continue
            if char.get("role", "").upper() != "MAIN":
                continue

            full_name = None

            # AniList API v2: name lives in node.name.full
            node = char.get("node", {})
            if isinstance(node, dict):
                name_data = node.get("name", {})
                if isinstance(name_data, dict):
                    full_name = name_data.get("full") or name_data.get("native")

            # Fallback: name stored directly at edge level
            if not full_name:
                name_data = char.get("name")
                if isinstance(name_data, dict):
                    full_name = name_data.get("full") or name_data.get("native")
                elif isinstance(name_data, str) and name_data.strip():
                    full_name = name_data.strip()

            if full_name:
                names.append(full_name)

            if len(names) >= top_n:
                break

        return names

    @staticmethod
    def extract_key_staff(staff):
        """
        Extract key creative staff — Director, Original Creator, and Series
        Composition — formatted as "Name (Role)" strings.
        These roles give the embedding strong signals for creator-based
        queries (e.g. "anime directed by Satoshi Kon").
        """
        # Exact role matches only — "Animation Director", "Action Director" etc.
        # are too granular and add noise rather than search signal.
        KEY_ROLES = {"director", "original creator", "series composition"}

        try:
            if isinstance(staff, str):
                staff = json.loads(staff)
        except Exception:
            return []

        if not isinstance(staff, list):
            return []

        results = []
        seen_names = set()

        for member in staff:
            if not isinstance(member, dict):
                continue

            role = member.get("role", "")
            if not any(k in role.lower() for k in KEY_ROLES):
                continue

            # Staff name lives inside node.name.full
            node = member.get("node", {})
            if not isinstance(node, dict):
                continue

            name_data = node.get("name", {})
            full_name = None
            if isinstance(name_data, dict):
                full_name = name_data.get("full") or name_data.get("native")
            elif isinstance(name_data, str) and name_data.strip():
                full_name = name_data.strip()

            if full_name and full_name not in seen_names:
                seen_names.add(full_name)
                results.append(f"{full_name} ({role})")

        return results

    # ----------------------------
    # MAIN PREPROCESSING
    # ----------------------------

    def preprocess(self):
        df = self.raw_data.copy()

        #df['idMal'] = df['idMal'].astype('Int64')
        

        # Clean description
        df["description"] = df["description"].apply(self.clean_description)

        # Filter out music
        df = df[df["format"] != "MUSIC"].reset_index(drop=True)

        # Parse JSON / list-like columns.
        # characters and staff are now included so build_embedding_text
        # can extract character names and key staff roles.
        parse_cols = [
            "synonyms", "genres", "rankings",
            "tags", "studios", "recommendations",
            "characters", "staff",
        ]

        for col in parse_cols:
            df[col] = df[col].apply(self.parse_json) ## ---> This is giving me an issue. It does not parse well

        # Removing empty description entries
        df = df[~df["description"].isna()].reset_index(drop=True)

        # Filter by relationship usefulness
        df = df[df["relations"].apply(self.should_keep_entry)].reset_index(drop=True)

        # Relationship classification
        df["relationship_type"] = df["relations"].apply(self.classify_relationship)

        # Build embedding name set
        df["name_set"] = df.apply(self.build_name_set, axis=1)
        df["name_text"] = df["name_set"].apply(
            lambda x: " | ".join(x) if x else ""
        )

        # Build final embedding text
        df["embedding_text"] = df.apply(self.build_embedding_text, axis=1)

        return self._split_tables(df)

    # ----------------------------
    # Table splitters
    # ----------------------------

    def _split_tables(self, df):

        anime_core = df[
            [
                "id",
                "idMal",
                "siteUrl",
                "title_english",
                "title_romaji",
                "title_native",
                "title_userPreferred",
                "synonyms",
                "coverImage_large",
                "coverImage_medium",
                "bannerImage",
            ]
        ].copy()

        anime_content = df[
            [
                "id",
                "description",
                "genres",
                "tags",
                "format",
                "source",
                "countryOfOrigin",
                "isAdult",
                "studios",
                "relationship_type",
            ]
        ].copy()

        anime_temporal = df[
            [
                "id",
                "season",
                "seasonYear",
                "episodes",
                "duration",
                "status",
                "startDate_year",
                "endDate_year",
            ]
        ].copy()

        anime_metrics = df[
            [
                "id",
                "averageScore",
                "meanScore",
                "popularity",
                "favourites",
                "trending",
                "rankings",
                "recommendations",
            ]
        ].copy()

        anime_embedding = df[
            [
                "id",
                "embedding_text"
            ]
        ].copy()

        return {
            "anime_core": anime_core,
            "anime_content": anime_content,
            "anime_temporal": anime_temporal,
            "anime_metrics": anime_metrics,
            "anime_embedding": anime_embedding,
        }
