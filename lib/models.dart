class Plant {
  final String id, name, scientific, family, category, symbol, description;
  final Map<String, String> sections;
  const Plant({
    required this.id,
    required this.name,
    required this.scientific,
    required this.family,
    required this.category,
    required this.symbol,
    required this.description,
    required this.sections,
  });
}

const pending = <String, String>{
  'Local names & knowledge': 'Malawian names and reported uses are awaiting community verification. Records should include language, district, plant part, attribution and permission. A traditional belief does not establish that a plant cures disease.',
  'Medicinal research': 'No therapeutic claim has been reviewed in this demonstration. A verified record will distinguish isolated compounds, laboratory studies, clinical evidence and approved medicines. Do not infer that a flower itself can safely replace a manufactured drug.',
  'Malawi distribution': 'District occurrence, native or introduced status, habitat and altitude have not been verified. This sample catalogue does not establish that this species occurs in Malawi.',
  'Growing conditions': 'Species-specific sunlight, temperature, soil, rainfall and drainage information is pending horticultural review.',
  'Plant care & treatment': 'Watering, propagation, pruning, flowering season and pest management are pending review. Confirm the plant identity before applying a treatment.',
  'Effects & precautions': 'Do not eat or prepare medicine from an unidentified plant. Photo identification can be wrong. Toxicity, drug interactions, allergies and risks for children, pregnancy and breastfeeding require qualified review.',
  'Legal & conservation': 'No legal status has been assessed. Protected status, collection and harvesting permits, trade restrictions and medicine manufacturing rules need current Malawi authority references. This app does not grant permission to harvest or sell plants.',
  'Sources & review': 'Draft interface record. No clinical, cultural, distribution or legal sources attached. Review status: not verified. Last content review: not yet performed.',
};
const plants = <Plant>[
  Plant(
    id: 'hibiscus',
    name: 'Hibiscus',
    scientific: 'Hibiscus rosa-sinensis',
    family: 'Malvaceae',
    category: 'Garden flowers',
    symbol: '🌺',
    description: 'A sample flowering-plant profile for exploring FloraMW. Confirm the species with a qualified botanist before relying on an identification.',
    sections: pending,
  ),
  Plant(
    id: 'periwinkle',
    name: 'Madagascar periwinkle',
    scientific: 'Catharanthus roseus',
    family: 'Apocynaceae',
    category: 'Research interest',
    symbol: '🌸',
    description: 'A sample botanical profile. Research interest is a catalogue label, not an endorsement of ingestion or home treatment.',
    sections: pending,
  ),
  Plant(
    id: 'marigold',
    name: 'African marigold',
    scientific: 'Tagetes erecta',
    family: 'Asteraceae',
    category: 'Garden flowers',
    symbol: '🌼',
    description: 'Explore the structure of a flower record, from identification to responsible care and verified local knowledge.',
    sections: pending,
  ),
  Plant(
    id: 'frangipani',
    name: 'Frangipani',
    scientific: 'Plumeria rubra',
    family: 'Apocynaceae',
    category: 'Flowering trees',
    symbol: '🌿',
    description: 'A flowering-tree demonstration record with space for habitat, seasonal features and conservation information.',
    sections: pending,
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
