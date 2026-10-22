from pydantic import BaseModel, Field, HttpUrl
from typing import Literal
class AnalyzeRequest(BaseModel):
    headline: str = Field(min_length=3, max_length=500)
    article_text: str | None = Field(default=None, max_length=50000)
    summary_length: Literal["short", "medium", "detailed"] = "medium"
    style: str = Field(default="editorial illustration", max_length=100)
class SummaryRequest(BaseModel):
    text: str = Field(min_length=30, max_length=50000)
    length: Literal["short", "medium", "detailed"] = "medium"
class GenerateRequest(AnalyzeRequest):
    image_prompt: str | None = Field(default=None, max_length=3000)
    aspect_ratio: Literal["1:1", "4:3", "3:2", "16:9"] = "16:9"
class UrlRequest(BaseModel):
    url: HttpUrl
