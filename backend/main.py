import os
from fastapi import FastAPI, Depends, HTTPException, status, Security, Query
from fastapi.security.api_key import APIKeyHeader
from pydantic import BaseModel
from backend.rag_pipeline.rag_pipeline import rag_pipeline
#from .rag_pipeline.rag_pipeline import rag_pipeline
from typing import Annotated
from collections import defaultdict
from datetime import timedelta, datetime

app = FastAPI(title="Anime Recommendation API")

# backend\rag_pipeline\rag_pipeline.py

API_KEY = os.getenv("MY_API_KEY")
api_key_header = APIKeyHeader(name="access_token", auto_error=True)


# ----------------------
# RATE LIMITING
# ----------------------

class RateLimiter:
    def __init__(self, requests_num: int = 20, period: timedelta = timedelta(minutes=1)):
        self.requests_per_min = requests_num
        self.period = period
        self.requests = defaultdict(list)

    def is_rate_limited(self, api_key: str) -> tuple[bool, int]:
        now = datetime.now()
        start_time = now - self.period
        self.requests[api_key] = [
            required_time for required_time in self.requests[api_key]
            if required_time > start_time
        ]

        recent_requests = len(self.requests[api_key])
        if recent_requests >= self.requests_per_min:
            return True, 0
        else:
            self.requests[api_key].append(now)
            return False, self.requests_per_min - recent_requests - 1



# ----------------------
# API KEY SECURITY
# ----------------------
rate_limiter = RateLimiter()


async def get_api_key(api_key: str = Security(api_key_header)):
    if api_key != API_KEY:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid or missing API key"
            )

    is_limited, _ = rate_limiter.is_rate_limited(api_key)
    if is_limited:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded. Try again later."
            )
    
    return api_key




# ----------------------
# REQUEST MODEL
# ----------------------

class RecommendRequest(BaseModel):
    query: Annotated[str, Query(description="The query to recommend anime for", min_length=2)]
    top_k: int = 20
    allow_adult: bool = False

class RecommendResponse(BaseModel):
    query: str
    count: int
    allowed_adult: bool
    results: list
    extra: dict


# ----------------------
# ENDPOINTS
# ----------------------

@app.get("/")
async def root():
    return {"message": "Welcome to the Anime Recommendation API. Use the /recommend endpoint to get recommendations."}



@app.post("/recommend", response_model=RecommendResponse)
async def recommend(
    request: RecommendRequest,
    api_key: str = Depends(get_api_key)
):
    results, timings = rag_pipeline(
        query=request.query,
        top_k=request.top_k,
        allow_adult=request.allow_adult
    )

    return RecommendResponse(
        query=request.query,
        count=len(results),
        allowed_adult=request.allow_adult,
        results=results,
        extra={
            "timings": timings,
            "total_ms": sum(timings.values())
            }
        )


    


"""
import os
from fastapi import FastAPI, Query, Security, Depends, HTTPException, status
from fastapi.security.api_key import APIKeyHeader
from serving.rag_pipeline import rag_pipeline
from pydantic import BaseModel
from typing import Annotated



app = FastAPI()

# ----------------------
# API KEY SECURITY
# ----------------------

API_KEY = os.getenv('MY_API_KEY')

api_key_header = APIKeyHeader(name="access_token")

async def get_api_key(api_key: str = Security(api_key_header)):
    if api_key == API_KEY:
        return api_key
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN, detail="Could not validate credentials"
    )


# ----------------------
# REQUEST MODEL
# ----------------------


class RecommendRequest(BaseModel):
    #query: Annotated[str, Query(description="The query to recommend anime for", min_length=2, alias="User Query")]
    query: str
    top_k: int = 20
    allow_adult: bool = False


# ----------------------
# ENDPOINTS
# ----------------------


@app.post("/recommend")
async def recommend(
    request: RecommendRequest, 
    api_key: str = Depends(get_api_key)):

    output, _ = rag_pipeline(
        query=request.query,
        top_k=request.top_k,
        allow_adult=request.allow_adult)
    return {
        "query": request.query,
        "count": len(output),
        "results": output}
"""