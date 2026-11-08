# Language support and review

FloraMW supports selecting English, Chichewa, Yao, Tumbuka, Sena, Lhomwe and Tonga. The interface uses resource-backed text with English fallback; a small Chichewa navigation vocabulary is a draft. The remaining packs are intentionally awaiting native wording, not fabricated translations.

`assets/translations.json` contains the English source catalogue and language maps. Add a translated value under the exact English key in the selected pack. Keep each string understandable in a button or field, preserve scientific names, and verify on a narrow phone with large text. Native/local variants and orthography must be agreed with the relevant community. The Malawi-specific identifiers are `swk` (Sena), `lon` (Lhomwe) and `tog` (Tonga). Older local preferences using `seh`/`ngl` are migrated. The language names remain Sena and Lhomwe in the selector.

Settings → Language packs & translation review shows available and missing phrases. Users can save local wording on their own device. These are unreviewed local overrides, not submissions or globally published translations. No backend is involved. Source names, scientific names, lengthy botanical/safety prose, field hints and dynamic messages require separate content review; a phrase-count indicator is not an accuracy score.

Clinical risks and legal information should be translated by appropriately qualified speakers, then checked against the source. Do not imply that local selection establishes full language coverage. The visible English-fallback notice must remain until the relevant pack is complete and reviewed.
