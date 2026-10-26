from pydantic import BaseModel, Field

class AskRequest(BaseModel):
    question: str = Field(min_length=3, max_length=3000)
    use_search: bool = True

class LoginRequest(BaseModel):
    password: str = Field(min_length=1, max_length=200)

class Source(BaseModel):
    name: str
    url: str | None = None

class AskResponse(BaseModel):
    success: bool
    answer: str
    sources: list[Source]
    out_of_scope: bool = False
