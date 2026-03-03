import re
from typing import Dict, Tuple
from .types import HttpRouteHandler
from .methods import Methods

MATCHING_TYPES = {
    'alphanumeric': r'\w+',
    'path': r'[\w/]+',
    'any': r'.+',
    'filepath': r'(?!\/)(?!.*\/\.+\/)[\/aA-zZ0-9 \.]+'
}

def check_and_extract(path: str, pattern: str):
    escaped_pattern = re.escape(pattern)
    
    for type_name, regex in MATCHING_TYPES.items():
        escaped_pattern = escaped_pattern.replace(re.escape(f"{{{type_name}}}"), f"({regex})")
    
    escaped_pattern = escaped_pattern.replace(re.escape("{}"), f"({MATCHING_TYPES['any']})")
    match = re.match(f"^{escaped_pattern}$", path)
    
    if match:
        return match.groups()
    else:
        return None

def match_route(path: str, route_dict: Dict[str, HttpRouteHandler]):
    for route, handler in route_dict.items():
        if (groups := check_and_extract(path, route)) is not None:
            return handler, groups
    return None, None

def match_route_with_method(path: str, method: Methods, route_dict: Dict[Tuple[str, Methods], HttpRouteHandler]):    
    for route, handler in route_dict.items():
        if route[1] == method and (groups := check_and_extract(path, route[0])) is not None:
            return handler, groups
    return None, None