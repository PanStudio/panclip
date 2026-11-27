import pytest

from panclip.core.redact import redact

SECRETS = [
    ("OPENAI_API_KEY=sk-proj-abcdefghijklmnopqrstuvwxyz0123456789", "api_key"),
    ("export AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE", "aws_access_key"),
    ("token: ghp_" + "a1" * 18, "github_token"),
    ("glpat-abcdefghij0123456789", "gitlab_token"),
    ("xoxb-1234567890-abcdefghij", "slack_token"),
    (
        "-----BEGIN RSA PRIVATE KEY-----\nMIIEow\n-----END RSA PRIVATE KEY-----",
        "private_key",
    ),
    ("Authorization: Bearer abcdef1234567890abcdef", "auth_header"),
    ("postgres://admin:s3cretPass@db.example.com/app", "url_password"),
    ("redis://:s3cretPass@localhost:6379/0", "url_password"),
    ("https://x.io/cb?page=2&access_token=abc123def456", "url_query_secret"),
    ("DB_PASSWORD=supersecret", "secret_assignment"),
    ('password = "hunter22"', "secret_assignment"),
    ('session_id = "Zk3qP9xLm2Vb7Rt5Yw8Nc4Hd"', "high_entropy"),
    (
        "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0."
        "dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U",
        "jwt",
    ),
]


@pytest.mark.parametrize("text,kind", SECRETS)
def test_secret_is_replaced(text, kind):
    redacted, counts = redact(text)
    assert f"[REDACTED:{kind}]" in redacted
    assert counts == {kind: 1}


@pytest.mark.parametrize(
    "text",
    [
        "self.password = password_input",
        "password: str",
        'api_key = os.environ["OPENAI_API_KEY"]',
        "token = get_token()",
        'class_name = "MyVeryLongClassName2024"',
        "commit = 8b143e7c0ee44441f7896abcdef0123456789abc",
        "def main():\n    print('hello')",
    ],
)
def test_ordinary_code_is_kept(text):
    assert redact(text) == (text, {})


def test_assignment_keeps_its_quotes_and_key():
    assert redact("secret: 'abc123xyz'")[0] == "secret: '[REDACTED:secret_assignment]'"
