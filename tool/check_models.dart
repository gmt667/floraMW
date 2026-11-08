// Local-only checks; imports no Flutter runtime and makes no network requests.
import '../lib/models.dart';
import '../lib/locale_data.dart';

void check(bool value, String label) {
  if (!value) throw StateError(label);
  print('PASS $label');
}

Future<void> main() async {
  check(
    allDistricts.length == 28 && allDistricts.toSet().length == 28,
    '28 distinct districts',
  );
  check(
    districtsByRegion['Northern']!.length == 6 &&
        districtsByRegion['Central']!.length == 9 &&
        districtsByRegion['Southern']!.length == 13,
    'region counts 6 / 9 / 13',
  );
  check(
    languageNames.length == 7 &&
        languageNames.values.toSet().containsAll([
          'Chichewa',
          'Yao',
          'Tumbuka',
          'Sena',
          'Lhomwe',
          'Tonga',
        ]),
    'all requested language choices',
  );
  check(
    localized('yao', 'Settings') == 'Settings',
    'explicit English fallback for pending translations',
  );
  final d = Discovery(
    id: '1',
    plantId: 'hibiscus',
    createdAt: '2026-11-08T10:00:00',
    district: 'Rumphi',
    note: 'Field note',
  );
  final restored = Discovery.fromJson(d.toJson());
  check(
    restored.district == 'Rumphi' && restored.note == 'Field note',
    'district and journal roundtrip',
  );
  final service = DemoIdentificationService();
  final candidates = await service.identify(
    'unrelated-photo',
    DemoOutcome.matches,
  );
  check(
    candidates.isDemo && candidates.candidateIds.length == 3,
    'sample candidates remain labelled demo',
  );
  check(
    (await service.identify(null, DemoOutcome.noMatch)).candidateIds.isEmpty,
    'no-match state',
  );
  bool error = false;
  try {
    await service.identify(null, DemoOutcome.error);
  } catch (_) {
    error = true;
  }
  check(error, 'service-error state');
  check(
    plants.every((p) => p.sections.length >= 8),
    'complete profile section structure',
  );
}
