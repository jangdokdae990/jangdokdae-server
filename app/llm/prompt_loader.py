"""프롬프트 YAML 파일 로더"""
import logging
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)


class PromptLoader:
    """YAML 프롬프트 파일 로더"""

    def __init__(self, prompts_dir: str | None = None):
        # 기본값은 프로젝트 루트의 prompts/ — CWD 의존을 피하기 위해 절대 경로 사용
        if prompts_dir is None:
            self.prompts_dir = Path(__file__).parent.parent.parent / "prompts"
        else:
            self.prompts_dir = Path(prompts_dir)
        self._cache = {}

    def load(self, prompt_name: str) -> dict:
        """프롬프트 파일 로드"""
        if prompt_name in self._cache:
            return self._cache[prompt_name]

        prompt_file = self.prompts_dir / f"{prompt_name}.yaml"

        if not prompt_file.exists():
            logger.error(f"프롬프트 파일을 찾을 수 없음: {prompt_file}")
            raise FileNotFoundError(f"Prompt file not found: {prompt_file}")

        try:
            with open(prompt_file, "r", encoding="utf-8") as f:
                prompt_data = yaml.safe_load(f)
            self._cache[prompt_name] = prompt_data
            logger.info(f"프롬프트 로드: {prompt_name} (v{prompt_data.get('version')})")
            return prompt_data
        except yaml.YAMLError as e:
            logger.error(f"프롬프트 파싱 오류: {e}")
            raise

    def get_template(self, prompt_name: str) -> str:
        """프롬프트 템플릿 문자열 반환"""
        prompt_data = self.load(prompt_name)
        return prompt_data.get("template", "")

    def get_config(self, prompt_name: str) -> dict:
        """프롬프트 설정 반환 (model, temperature, max_tokens 등)"""
        prompt_data = self.load(prompt_name)
        return {
            "model": prompt_data.get("model"),
            "temperature": prompt_data.get("temperature", 0.7),
            "max_tokens": prompt_data.get("max_tokens", 1000),
        }

    def format_prompt(self, prompt_name: str, **kwargs) -> str:
        """변수를 포함한 프롬프트 포매팅"""
        template = self.get_template(prompt_name)
        try:
            return template.format(**kwargs)
        except KeyError as e:
            logger.error(f"프롬프트 포매팅 오류 - 누락된 변수: {e}")
            raise ValueError(f"Missing parameter: {e}")
