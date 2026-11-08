# Device acceptance checklist

Automated test results are recorded in README. Physical-device checks remain necessary.

- Android and iOS: launch icon, native launch background, Flutter welcome pages, skip/continue, repeat launch.
- Camera/gallery: consent cancel, system picker cancel, permission refusal, image selection, camera unavailable, Android lost-data recovery.
- Demo results: loading, cancel, candidates, no match, service failure, retry, repeated request, navigate away during loading.
- Confirm no candidate claims to identify the submitted photograph.
- Search by common/scientific name/family; clear; category filter; A-Z/Z-A; no results/reset.
- Open profile, expand all sections, toggle bookmark from profile and garden.
- Save discovery with a photo; restart app; verify image and notes; delete discovery; verify original gallery photo remains.
- Correction validation; save draft; restart; view/delete; confirm no submission claim.
- Dark mode; large text plus system font scaling; narrow phone; landscape; screen reader names and focus; sufficient contrast.
- Clear local records removes saved photos, notes, bookmarks and drafts while retaining theme/language.
- Disconnect network: all bundled frontend features remain available.
- District setup: search/select all 28 entries; verify preference and journal snapshot after restart.
- All seven language choices persist; English fallback is visibly disclosed. Review every translation with native speakers before release.
- Low storage or missing photo: visible recoverable error; existing records remain understandable.
