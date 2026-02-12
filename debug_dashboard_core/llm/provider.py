"""LLMProvider — LiteLLM wrapper with fallback logic and cost tracking.

Supports 100+ models via LiteLLM:
  - anthropic/claude-sonnet-4-20250514
  - openai/gpt-4o
  - gemini/gemini-2.0-flash
  - ollama/llama3  (local, free)
  - and many more

LiteLLM is lazily imported. If not installed, is_available returns False
and Tier 1 continues working without LLM.
"""
import logging
import time
from typing import Optional

from ..agent.events import LLMAnalysis
from .prompts import build_analysis_prompt, build_report_prompt, parse_analysis_response
from .cost import CostTracker

logger = logging.getLogger("llm.provider")


class LLMProvider:
    """Multi-LLM provider using LiteLLM.

    Config example (in config.yaml):
        llm:
          model: "anthropic/claude-sonnet-4-20250514"
          fallback_model: "ollama/llama3"
          api_key_env: "ANTHROPIC_API_KEY"
          temperature: 0.3
          max_tokens: 2000
          timeout_seconds: 30
          daily_budget_usd: 5.0
    """

    def __init__(self, config: dict):
        self._config = config.get("llm", {})
        self._model = self._config.get("model", "")
        self._fallback = self._config.get("fallback_model", "")
        self._temperature = self._config.get("temperature", 0.3)
        self._max_tokens = self._config.get("max_tokens", 2000)
        self._timeout = self._config.get("timeout_seconds", 30)
        self._cost_tracker = CostTracker(
            daily_limit=self._config.get("daily_budget_usd", 5.0)
        )
        self._litellm = None

    def _ensure_litellm(self):
        """Lazy import litellm — only when actually needed."""
        if self._litellm is None:
            try:
                import litellm
                self._litellm = litellm
                # Suppress litellm's verbose logging
                litellm.suppress_debug_info = True
            except ImportError:
                raise RuntimeError(
                    "litellm is not installed. "
                    "Install it with: pip install litellm"
                )

    @property
    def is_available(self) -> bool:
        """Check if LLM is configured and litellm is installed."""
        if not self._model:
            return False
        try:
            self._ensure_litellm()
            return True
        except RuntimeError:
            return False

    @property
    def model_name(self) -> str:
        return self._model

    @property
    def budget_remaining(self) -> float:
        return self._cost_tracker.remaining_today

    def analyze_report(
        self, checker_name: str, report: dict, config: dict,
        evidence_context: dict = None
    ) -> LLMAnalysis:
        """Run LLM analysis on a checker report.

        Args:
            checker_name: name of the checker
            report: PhaseReport.to_dict() output
            config: workspace config
            evidence_context: from AgentMemory.get_context_for_llm()

        Returns:
            LLMAnalysis with root causes, fix suggestions, cost info
        """
        self._ensure_litellm()

        if not self._cost_tracker.can_spend():
            return LLMAnalysis(
                request_id="budget_exceeded",
                checker_name=checker_name,
                prompt_tokens=0,
                completion_tokens=0,
                cost_usd=0,
                model_used=self._model,
                analysis_text="Daily budget exceeded. Analysis skipped.",
                root_causes=[],
                fix_suggestions=[],
                evidence_summary={"budget_exceeded": True},
            )

        prompt = build_analysis_prompt(checker_name, report, config, evidence_context)
        model = self._model

        try:
            response = self._litellm.completion(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=self._temperature,
                max_tokens=self._max_tokens,
                timeout=self._timeout,
            )
        except Exception as e:
            logger.warning(f"Primary model failed ({model}): {e}")
            if self._fallback:
                logger.info(f"Trying fallback: {self._fallback}")
                model = self._fallback
                try:
                    response = self._litellm.completion(
                        model=model,
                        messages=[{"role": "user", "content": prompt}],
                        temperature=self._temperature,
                        max_tokens=self._max_tokens,
                        timeout=self._timeout,
                    )
                except Exception as e2:
                    raise RuntimeError(
                        f"Both primary ({self._model}) and fallback ({self._fallback}) failed: {e2}"
                    )
            else:
                raise

        # Extract usage and cost
        usage = response.usage if hasattr(response, 'usage') else None
        prompt_tokens = usage.prompt_tokens if usage else 0
        completion_tokens = usage.completion_tokens if usage else 0

        try:
            cost = self._litellm.completion_cost(completion_response=response)
        except Exception:
            cost = 0.0

        self._cost_tracker.record(cost, model=model)

        text = response.choices[0].message.content
        parsed = parse_analysis_response(text)

        return LLMAnalysis(
            request_id=getattr(response, 'id', '') or "",
            checker_name=checker_name,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost_usd=cost,
            model_used=model,
            analysis_text=parsed.get("analysis", text),
            root_causes=parsed.get("root_causes", []),
            fix_suggestions=parsed.get("fix_suggestions", []),
            evidence_summary={
                "prompt_length": len(prompt),
                "has_evidence_context": evidence_context is not None,
                "regressions_count": len((evidence_context or {}).get("regressions", [])),
            },
        )

    def generate_report(self, scan_data: dict) -> str:
        """Generate natural language report from scan data."""
        self._ensure_litellm()
        prompt = build_report_prompt(scan_data)
        # Use higher max_tokens for comprehensive overview
        overview_max = max(self._max_tokens, 4000)
        response = self._litellm.completion(
            model=self._model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.4,
            max_tokens=overview_max,
            timeout=max(self._timeout, 60),
        )
        try:
            cost = self._litellm.completion_cost(completion_response=response)
        except Exception:
            cost = 0.0
        self._cost_tracker.record(cost, model=self._model)
        return response.choices[0].message.content
