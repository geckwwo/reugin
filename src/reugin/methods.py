import enum

class Methods(enum.Enum):
    GET = "GET"
    POST = "POST"
    HEAD = "HEAD"
    OPTIONS = "OPTIONS"
    TRACE = "TRACE"
    PUT = "PUT"
    DELETE = "DELETE"
    PATCH = "PATCH"