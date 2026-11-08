class PlantSource {
  final String title, url;
  const PlantSource(this.title, this.url);
}

class Plant {
  final String id, name, scientific, family, category, symbol, description;
  final Map<String, String> sections;
  final List<PlantSource> sources;
  String get photoAsset => "assets/plants/$id.jpg";
  const Plant({
    required this.id,
    required this.name,
    required this.scientific,
    required this.family,
    required this.category,
    required this.symbol,
    required this.description,
    required this.sections,
    this.sources = const [],
  });
}

const pending = <String, String>{
  'Local names & knowledge':
      'Malawian names and reported uses are awaiting community verification. Records should include language, district, plant part, attribution and permission. A traditional belief does not establish that a plant cures disease.',
  'Medicinal research':
      'No therapeutic claim has been reviewed in this demonstration. A verified record will distinguish isolated compounds, laboratory studies, clinical evidence and approved medicines. Do not infer that a flower itself can safely replace a manufactured drug.',
  'Malawi distribution':
      'District occurrence, native or introduced status, habitat and altitude have not been verified. This sample catalogue does not establish that this species occurs in Malawi.',
  'Growing conditions':
      'Species-specific sunlight, temperature, soil, rainfall and drainage information is pending horticultural review.',
  'Plant care & treatment':
      'Watering, propagation, pruning, flowering season and pest management are pending review. Confirm the plant identity before applying a treatment.',
  'Effects & precautions':
      'Do not eat or prepare medicine from an unidentified plant. Photo identification can be wrong. Toxicity, drug interactions, allergies and risks for children, pregnancy and breastfeeding require qualified review.',
  'Legal & conservation':
      'No legal status has been assessed. Protected status, collection and harvesting permits, trade restrictions and medicine manufacturing rules need current Malawi authority references. This app does not grant permission to harvest or sell plants.',
  'Sources & review':
      'Public botanical sources checked on 8 November 2026. This is an educational summary, not an independent botanical or clinical review. Malawi district occurrence and local traditional uses remain unverified. Open the source links below for context.',
};
const legalSummary =
    'Malawi’s Pharmacy and Medicines Regulatory Authority regulates medicines and traditional medicinal products. Consult PMRA before manufacturing or marketing a medicine. Species-specific harvesting permissions and protected status are not assessed here. A plant profile is not a permit.';
const pmraSource = PlantSource(
  'PMRA · mandate and regulated products',
  'https://www.pmra.mw/who-we-are/',
);
final plants = <Plant>[
  Plant(
    id: 'hibiscus',
    name: 'Chinese hibiscus',
    scientific: 'Hibiscus rosa-sinensis',
    family: 'Malvaceae',
    category: 'Garden flowers',
    symbol: '🌺',
    description:
        'A tropical evergreen shrub in the mallow family, known for large flowers with a prominent central floral tube.',
    sections: {
      ...pending,
      'Identifying features':
          'Large funnel-shaped flowers; a conspicuous central floral tube; glossy leaves with toothed edges. Cultivars vary. These features alone do not confirm an identification.',
      'Growing conditions':
          'NC State Extension describes sun to partial shade and fertile, moist soil that drains well. Protect from frost and strong wind. This general care guidance is not a Malawi district suitability assessment.',
      'Plant care & treatment':
          'Keep the root zone moist without waterlogging. Stem cuttings are used for propagation. Watch for scale insects. Obtain local horticultural advice before using pesticides.',
      'Medicinal research':
          'No approved medicinal use is asserted for this species in FloraMW. Do not confuse it with other Hibiscus species or transfer claims about a different species to this flower.',
      'Legal & conservation': legalSummary,
    },
    sources: [
      PlantSource(
        'NC State Extension · Chinese hibiscus',
        'https://plants.ces.ncsu.edu/plants/hibiscus-rosa-sinensis/',
      ),
      pmraSource,
    ],
  ),
  Plant(
    id: 'periwinkle',
    name: 'Madagascar periwinkle',
    scientific: 'Catharanthus roseus',
    family: 'Apocynaceae',
    category: 'Research interest',
    symbol: '🌸',
    description:
        'A flowering plant with glossy opposite leaves and typically five spreading flower lobes. Its medicinal compounds do not make the whole plant safe to consume.',
    sections: {
      ...pending,
      'Identifying features':
          'Opposite glossy leaves with a pale midrib and flowers with a narrow tube opening into five broad lobes. Pink and white forms occur. Compare multiple features and seek expert confirmation.',
      'Growing conditions':
          'NC State Extension describes sun to partial shade and freely draining soil. It tolerates heat and some dry conditions. Avoid persistently wet roots.',
      'Plant care & treatment':
          'Seed propagation is common. Some cultivars resist certain fungal problems; cultivar resistance does not mean immunity. Seek horticultural advice for rot or blight.',
      'Medicinal research':
          'The US National Cancer Institute identifies vinblastine as a plant-derived alkaloid from Catharanthus roseus. Vincristine is a related chemotherapy drug. These are manufactured medicines used under specialist care; consuming the plant is not a cancer treatment.',
      'Effects & precautions':
          'Queensland Poisons Information Centre describes all parts as toxic. Ingestion can cause illness. Do not make teas, extracts or home remedies from this plant. If exposure causes symptoms, seek medical attention.',
      'Legal & conservation': legalSummary,
    },
    sources: [
      PlantSource(
        'NC State Extension · periwinkle care and features',
        'https://plants.ces.ncsu.edu/plants/catharanthus-roseus/',
      ),
      PlantSource(
        'National Cancer Institute · vinblastine sulfate',
        'https://www.cancer.gov/publications/dictionaries/cancer-drug/def/vinblastine-sulfate',
      ),
      PlantSource(
        'National Cancer Institute · vincristine sulfate',
        'https://www.cancer.gov/about-cancer/treatment/drugs/vincristinesulfate',
      ),
      PlantSource(
        'Queensland Health · periwinkle toxicity',
        'https://www.poisonsinfo.health.qld.gov.au/plants-and-mushrooms/periwinkle-catharanthus-roseus',
      ),
      pmraSource,
    ],
  ),
  Plant(
    id: 'marigold',
    name: 'African marigold',
    scientific: 'Tagetes erecta',
    family: 'Asteraceae',
    category: 'Garden flowers',
    symbol: '🌼',
    description:
        'An upright flowering annual with dense flower heads. Despite its common name, it originates from Mexico and Guatemala.',
    sections: {
      ...pending,
      'Identifying features':
          'Dense yellow or orange flower heads and divided aromatic leaves are useful comparison features. Cultivars differ, and similar marigolds can be confused.',
      'Growing conditions':
          'NC State Extension recommends full sun and well-drained soil, with reasonably even moisture. Light afternoon shade can be tolerated.',
      'Plant care & treatment':
          'Remove spent flower heads. Taller plants may need support from strong wind. Young shoots can be pinched for bushier growth. Look out for leaf spots, mildew and rot; avoid diagnosing a disease from a single image.',
      'Effects & precautions':
          'Sap can cause skin irritation; some plant compounds can cause reactions in contact with sunlight. Avoid contact with eyes and do not assume ornamental plants are edible.',
      'Legal & conservation': legalSummary,
    },
    sources: [
      PlantSource(
        'NC State Extension · African marigold',
        'https://plants.ces.ncsu.edu/plants/tagetes-erecta/',
      ),
      pmraSource,
    ],
  ),
  Plant(
    id: 'frangipani',
    name: 'Frangipani',
    scientific: 'Plumeria rubra',
    family: 'Apocynaceae',
    category: 'Flowering trees',
    symbol: '🌿',
    description:
        'A tropical flowering tree native from Mexico to Venezuela, according to Kew. A reference photograph is not evidence of local occurrence.',
    sections: {
      ...pending,
      'Identifying features':
          'A small tree with thick branches and clusters of flowers. Flower colour varies. Related Plumeria species can look similar, so check leaves and other features with a specialist.',
      'Growing conditions':
          'Singapore National Parks describes full sun, moderate watering and well-drained soil. This is general horticultural guidance, not a Malawi district planting guarantee.',
      'Plant care & treatment':
          'Poor drainage can encourage root rot. Scale insects and caterpillars are among reported pests. Prune for structure with appropriate protective equipment and local horticultural advice.',
      'Effects & precautions':
          'University of California guidance treats Plumeria plants as toxic and warns that sap can irritate skin. Wear gloves and protect eyes during pruning. Keep cut material away from children and pets.',
      'Legal & conservation': legalSummary,
    },
    sources: [
      PlantSource(
        'Kew · Plumeria rubra taxonomy and native range',
        'https://powo.science.kew.org/taxon/81275-1',
      ),
      PlantSource(
        'Singapore National Parks · frangipani care',
        'https://www.nparks.gov.sg/florafaunaweb/flora/3/0/3074',
      ),
      PlantSource(
        'University of California · Plumeria safety',
        'https://ucanr.edu/site/plant-safely-drought-tolerant-landscapes/plumeria-spp',
      ),
      pmraSource,
    ],
  ),
];
Plant plantById(String id) =>
    plants.firstWhere((p) => p.id == id, orElse: () => plants.first);

class Discovery {
  final String id, plantId, createdAt;
  final String? photo, district;
  String note;
  Discovery({
    required this.id,
    required this.plantId,
    required this.createdAt,
    this.photo,
    this.district,
    this.note = '',
  });
  Map<String, dynamic> toJson() => {
    'id': id,
    'plantId': plantId,
    'createdAt': createdAt,
    'photo': photo,
    'district': district,
    'note': note,
  };
  factory Discovery.fromJson(Map<String, dynamic> j) => Discovery(
    id: j['id'] as String,
    plantId: j['plantId'] as String,
    createdAt: j['createdAt'] as String,
    photo: j['photo'] as String?,
    district: j['district'] as String?,
    note: j['note'] as String? ?? '',
  );
}

enum DemoOutcome { matches, noMatch, error }

class IdentificationResult {
  final List<String> candidateIds;
  final bool isDemo;
  const IdentificationResult({
    required this.candidateIds,
    required this.isDemo,
  });
}

abstract class IdentificationService {
  Future<IdentificationResult> identify(String? photoPath, DemoOutcome outcome);
}

class DemoIdentificationService implements IdentificationService {
  @override
  Future<IdentificationResult> identify(
    String? photoPath,
    DemoOutcome outcome,
  ) async {
    await Future<void>.delayed(const Duration(milliseconds: 1200));
    if (outcome == DemoOutcome.error)
      throw Exception('Demonstration service failure');
    return IdentificationResult(
      candidateIds: outcome == DemoOutcome.noMatch
          ? []
          : ['hibiscus', 'periwinkle', 'marigold'],
      isDemo: true,
    );
  }
}
