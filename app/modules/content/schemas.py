from typing import Annotated, Literal

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, StringConstraints, field_validator

Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=240)]
Slug = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=180,
                                         pattern=r'^[a-z0-9]+(?:-[a-z0-9]+)*$')]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid')


class ArticleWrite(StrictModel):
    slug: Slug
    title: Title
    excerpt: Annotated[str, Field(max_length=1000)] = ''
    body: Annotated[str, Field(max_length=100000)] = ''
    is_published: bool = False


class ResourceWrite(StrictModel):
    resource_type: Literal['article', 'video', 'audio', 'pdf', 'guide']
    title: Title
    description: Annotated[str, Field(max_length=2000)] = ''
    url: AnyHttpUrl | None = None
    is_published: bool = False

    @field_validator('url')
    @classmethod
    def reject_url_credentials(cls, value: AnyHttpUrl | None):
        if value and (value.username or value.password):
            raise ValueError('Les identifiants ne sont pas autorisés dans une URL de ressource.')
        return value


