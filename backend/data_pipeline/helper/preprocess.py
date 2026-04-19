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
        text = re.sub('\""', '"', text)



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
        if pd.isna(x):
            return []
        if isinstance(x, list):
            return x
        if isinstance(x, dict):
            return [x]
        if isinstance(x, str):
            try:
                parsed = json.loads(x)
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

        if row.get("name_text"):
            parts.append(row["name_text"])

        if isinstance(row.get("description"), str):
            parts.append(row["description"])

        if isinstance(row.get("genres"), list) and row["genres"]:
            parts.append("Genres: " + ", ".join(row["genres"]))

        tag_names = Preprocessor.extract_tags(row.get("tags"))
        if tag_names:
            parts.append("Tags: " + ", ".join(sorted(tag_names)))

        return " ".join(parts)
    
    @staticmethod
    def extract_tags(tags):
        """
        Safely extract tag names from tags column
        """

        try:
            if isinstance(tags, str):
                tags = json.loads(tags)
        except Exception:
            return set()

        tag_names = set()
        for t in tags:
            tag_name = t.get("name")
            if tag_name:
                tag_names.add(tag_name)

        return tag_names

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

        # Parse JSON / list-like columns
        parse_cols = [
            "synonyms", "genres", "rankings",
            "tags", "studios", "recommendations"
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
