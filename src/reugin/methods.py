from enum import StrEnum


class Methods(StrEnum):
    GET = "GET"
    POST = "POST"
    HEAD = "HEAD"
    OPTIONS = "OPTIONS"
    TRACE = "TRACE"
    PUT = "PUT"
    DELETE = "DELETE"
    PATCH = "PATCH"
