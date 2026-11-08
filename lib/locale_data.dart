/// District names are stable UI identifiers; city councils are not extra districts.
const districtsByRegion = <String, List<String>>{
  'Northern': [
    'Chitipa',
    'Karonga',
    'Likoma',
    'Mzimba',
    'Nkhata Bay',
    'Rumphi',
  ],
  'Central': [
    'Dedza',
    'Dowa',
    'Kasungu',
    'Lilongwe',
    'Mchinji',
    'Nkhotakota',
    'Ntcheu',
    'Ntchisi',
    'Salima',
  ],
  'Southern': [
    'Balaka',
    'Blantyre',
    'Chikwawa',
    'Chiradzulu',
    'Machinga',
    'Mangochi',
    'Mulanje',
    'Mwanza',
    'Neno',
    'Nsanje',
    'Phalombe',
    'Thyolo',
    'Zomba',
  ],
};
final allDistricts = districtsByRegion.values.expand((v) => v).toList()..sort();
const languageNames = <String, String>{
  'en': 'English',
  'ny': 'Chichewa',
  'yao': 'Yao',
  'tum': 'Tumbuka',
  'seh': 'Sena',
  'ngl': 'Lhomwe',
  'tog': 'Tonga',
};

/// Only reviewed keys should replace the English fallback. Untranslated keys
/// remain visible in English rather than being passed off as translated text.
const navigationTranslations = <String, Map<String, String>>{
  'ny': {
    'Discover': 'Onani',
    'Identify': 'Zindikirani',
    'My garden': 'Munda wanga',
    'Settings': 'Zokonda',
    'What’s blooming?': 'Ndi duwa lanji?',
    'Take a photo': 'Jambulani chithunzi',
    'Choose from gallery': 'Sankhani chithunzi',
    'Identify a flower': 'Zindikirani duwa',
  },
  'yao': {},
  'tum': {},
  'seh': {},
  'ngl': {},
  'tog': {},
};
String localized(String language, String english) =>
    navigationTranslations[language]?[english] ?? english;
