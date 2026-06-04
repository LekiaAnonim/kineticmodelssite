"""drf-spectacular postprocessing hook: multi-language code samples.

Adds an ``x-codeSamples`` array (cURL, Python, R, MATLAB, JavaScript, Java) to
every operation in the OpenAPI schema, so ReDoc renders language tabs and the
docs show ready-to-run snippets. The base URL is taken from the first configured
SPECTACULAR ``SERVERS`` entry; the ``Authorization`` header uses a token
placeholder the reader replaces with their own API token.

Registered via ``SPECTACULAR_SETTINGS["POSTPROCESSING_HOOKS"]`` (alongside the
default enum-postprocessing hook, which must be kept).
"""

from django.conf import settings

TOKEN_PLACEHOLDER = "<your-api-token>"


def _base_url():
    servers = (getattr(settings, "SPECTACULAR_SETTINGS", {}) or {}).get("SERVERS") or []
    if servers and servers[0].get("url"):
        return servers[0]["url"].rstrip("/")
    return "http://localhost:8000"


def _curl(method, url, has_body):
    parts = [f"curl -X {method}", f'-H "Authorization: Token {TOKEN_PLACEHOLDER}"']
    if has_body:
        parts.append('-H "Content-Type: application/json"')
        parts.append("-d '{ }'")
    parts.append(f'"{url}"')
    return " \\\n  ".join(parts)


def _python(method, url, has_body):
    fn = method.lower()
    lines = [
        "import requests",
        "",
        f'url = "{url}"',
        f'headers = {{"Authorization": "Token {TOKEN_PLACEHOLDER}"}}',
        "",
    ]
    if has_body:
        lines.append(f"resp = requests.{fn}(url, headers=headers, json={{}})")
    else:
        lines.append(f"resp = requests.{fn}(url, headers=headers)")
    lines += ["resp.raise_for_status()", "print(resp.json())"]
    return "\n".join(lines)


def _r(method, url, has_body):
    lines = [
        "library(httr2)",
        "",
        f'resp <- request("{url}") |>',
        f'  req_headers(Authorization = "Token {TOKEN_PLACEHOLDER}") |>',
    ]
    if has_body:
        lines.append("  req_body_json(list()) |>")
    if method != "GET":
        lines.append(f'  req_method("{method}") |>')
    lines.append("  req_perform()")
    lines.append("resp_body_json(resp)")
    return "\n".join(lines)


def _matlab(method, url, has_body):
    lines = [f'opts = weboptions("HeaderFields", ["Authorization" "Token {TOKEN_PLACEHOLDER}"]);']
    if method == "GET":
        lines.append(f'data = webread("{url}", opts);')
    else:
        lines.append(f'opts.RequestMethod = "{method.lower()}";')
        body = "struct()" if has_body else "[]"
        lines.append(f'data = webwrite("{url}", {body}, opts);')
    return "\n".join(lines)


def _javascript(method, url, has_body):
    header = f'"Authorization": "Token {TOKEN_PLACEHOLDER}"'
    if has_body:
        header += ', "Content-Type": "application/json"'
    lines = [
        f'const res = await fetch("{url}", {{',
        f'  method: "{method}",',
        f"  headers: {{ {header} }},",
    ]
    if has_body:
        lines.append("  body: JSON.stringify({}),")
    lines += ["});", "const data = await res.json();", "console.log(data);"]
    return "\n".join(lines)


def _java(method, url, has_body):
    body_pub = (
        'HttpRequest.BodyPublishers.ofString("{}")'
        if has_body
        else "HttpRequest.BodyPublishers.noBody()"
    )
    lines = [
        "HttpClient client = HttpClient.newHttpClient();",
        "HttpRequest request = HttpRequest.newBuilder()",
        f'    .uri(URI.create("{url}"))',
        f'    .header("Authorization", "Token {TOKEN_PLACEHOLDER}")',
    ]
    if has_body:
        lines.append('    .header("Content-Type", "application/json")')
    lines += [
        f'    .method("{method}", {body_pub})',
        "    .build();",
        "HttpResponse<String> response = client.send(",
        "    request, HttpResponse.BodyHandlers.ofString());",
        "System.out.println(response.body());",
    ]
    return "\n".join(lines)


_GENERATORS = [
    ("shell", "cURL", _curl),
    ("python", "Python", _python),
    ("r", "R", _r),
    ("matlab", "MATLAB", _matlab),
    ("javascript", "JavaScript", _javascript),
    ("java", "Java", _java),
]

_METHODS = {"get", "post", "put", "patch", "delete"}


def add_code_samples(result, generator, request, public):
    """Inject ``x-codeSamples`` into every operation."""
    base = _base_url()
    for path, path_item in (result.get("paths") or {}).items():
        url = f"{base}{path}"
        for method, operation in path_item.items():
            if method.lower() not in _METHODS or not isinstance(operation, dict):
                continue
            m = method.upper()
            has_body = method.lower() in {"post", "put", "patch"}
            operation["x-codeSamples"] = [
                {"lang": lang, "label": label, "source": gen(m, url, has_body)}
                for lang, label, gen in _GENERATORS
            ]
    return result
