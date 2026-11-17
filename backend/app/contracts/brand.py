from pydantic import Field, model_validator

from .common import Contract, HexColor, ShortText, wcag_contrast


class Positioning(Contract):
    statement: ShortText
    value_proposition: ShortText
    differentiators: list[ShortText] = Field(min_length=2)


class Personality(Contract):
    traits: list[str] = Field(min_length=3, max_length=6)
    tone_of_voice: ShortText
    voice_dos: list[ShortText] = Field(min_length=2)
    voice_donts: list[ShortText] = Field(min_length=2)


class Messaging(Contract):
    tagline: str = Field(max_length=100)
    key_messages: list[ShortText] = Field(min_length=3)
    elevator_pitch: ShortText


class ColorPalette(Contract):
    primary: HexColor
    secondary: HexColor
    accent: HexColor
    background: HexColor
    surface: HexColor
    text: HexColor
    rationale: ShortText

    @model_validator(mode="after")
    def _readable(self):
        ratio = wcag_contrast(self.text, self.background)
        if ratio < 4.5:
            raise ValueError(
                f"text {self.text} on background {self.background} has contrast {ratio:.2f}; "
                "WCAG AA requires >= 4.5. Choose a darker/lighter text or background."
            )
        return self


class Typography(Contract):
    heading_font: str = Field(min_length=2)
    body_font: str = Field(min_length=2)
    heading_fallback: str = "serif"
    body_fallback: str = "sans-serif"
    usage_notes: ShortText


class LogoDirection(Contract):
    concept: ShortText
    style: ShortText
    usage_notes: ShortText


class ImageryGuidelines(Contract):
    photo_style: ShortText
    illustration_style: ShortText
    avoid: list[ShortText] = Field(min_length=1)


class UIDirection(Contract):
    style_keywords: list[str] = Field(min_length=3)
    layout_principles: list[ShortText] = Field(min_length=2)
    component_style: ShortText
    motion: ShortText


class BrandGuideline(Contract):
    revision: int = Field(default=1, ge=1)
    brand_name: str
    positioning: Positioning
    personality: Personality
    messaging: Messaging
    palette: ColorPalette
    typography: Typography
    logo: LogoDirection
    imagery: ImageryGuidelines
    ui_direction: UIDirection
    inspirations: list[ShortText] = Field(min_length=2)
    change_summary: str | None = None  # what changed vs. the previous revision
