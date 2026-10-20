"""Create Secret Manager versions for provider keys from the environment; never via Terraform."""

SECRETS = (
    "GROQ_API_KEY",
    "DAILY_API_KEY",
    "DEEPGRAM_API_KEY",
    "ELEVENLABS_API_KEY",
    "LANGFUSE_PUBLIC_KEY",
    "LANGFUSE_SECRET_KEY",
    "CAFE_NORTE_ACCESS_CODE",
)


def main() -> int:
    raise NotImplementedError


if __name__ == "__main__":
    raise SystemExit(main())
