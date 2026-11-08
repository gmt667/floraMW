import 'dart:convert';

import 'package:flutter/services.dart';

import '../localization.dart';

import 'package:flutter/material.dart';

import '../models.dart';
import '../store.dart';
import '../ui.dart';

class ProfileScreen extends StatelessWidget {
  final Plant plant;
  final AppStore store;
  const ProfileScreen({super.key, required this.plant, required this.store});
  @override
  Widget build(BuildContext context) => ListenableBuilder(
    listenable: store,
    builder: (context, _) => Scaffold(
      appBar: AppBar(
        title: const FloraText('Plant profile'),
        actions: [
          IconButton(
            tooltip: store.saved.contains(plant.id)
                ? 'Remove bookmark'
                : 'Save plant',
            onPressed: () => guarded(context, () => store.toggleSave(plant.id)),
            icon: Icon(
              store.saved.contains(plant.id)
                  ? Icons.bookmark
                  : Icons.bookmark_outline,
            ),
          ),
        ],
      ),
      body: ListView(
        padding: const EdgeInsets.all(24),
        children: [
          PlantArt(plant),
          const SizedBox(height: 20),
          const FloraText(
            'REFERENCE PROFILE · NOT A PHOTO MATCH',
            style: TextStyle(fontSize: 11, letterSpacing: 1.5),
          ),
          const SizedBox(height: 12),
          FloraText(
            plant.name,
            style: Theme.of(context).textTheme.headlineLarge,
          ),
          FloraText(
            plant.scientific,
            style: const TextStyle(fontStyle: FontStyle.italic, fontSize: 16),
          ),
          Wrap(
            spacing: 8,
            children: [
              Chip(label: FloraText(plant.family)),
              Chip(label: FloraText(plant.category)),
            ],
          ),
          FloraText(plant.description, style: const TextStyle(height: 1.6)),
          const SizedBox(height: 12),
          const Notice(
            'This reference profile is not a confirmed match for your photo. General summaries link to public sources; local knowledge and Malawi distribution still need field review.',
          ),
          ...plant.sections.entries.map(
            (e) => Card(
              elevation: 0,
              child: ExpansionTile(
                title: FloraText(e.key),
                subtitle: FloraText(
                  [
                        'Local names & knowledge',
                        'Malawi distribution',
                      ].contains(e.key)
                      ? 'Local verification pending'
                      : e.key == 'Medicinal research' &&
                            plant.id != 'periwinkle'
                      ? 'No treatment claim'
                      : 'Source-linked educational information',
                  style: const TextStyle(fontSize: 11),
                ),
                children: [
                  Padding(
                    padding: const EdgeInsets.fromLTRB(16, 0, 16, 20),
                    child: FloraText(
                      e.value,
                      style: const TextStyle(height: 1.6),
                    ),
                  ),
                ],
              ),
            ),
          ),
          const SizedBox(height: 20),
          Semantics(
            header: true,
            child: FloraText(
              'Sources & image credit',
              style: Theme.of(context).textTheme.titleLarge,
            ),
          ),
          ...plant.sources.map((s) => SourceLink(s.title, s.url)),
          PhotoCredits(plantId: plant.id),
          const SizedBox(height: 12),
          OutlinedButton.icon(
            onPressed: () => Navigator.push(
              context,
              MaterialPageRoute<void>(
                builder: (_) => ReportScreen(store: store, plantId: plant.id),
              ),
            ),
            icon: const Icon(Icons.flag_outlined),
            label: const FloraText('Suggest a correction'),
          ),
        ],
      ),
    ),
  );
}

class ReportScreen extends StatefulWidget {
  final AppStore store;
  final String? plantId;
  const ReportScreen({super.key, required this.store, this.plantId});
  @override
  State<ReportScreen> createState() => _ReportScreenState();
}

class _ReportScreenState extends State<ReportScreen> {
  final form = GlobalKey<FormState>();
  final details = TextEditingController();
  final source = TextEditingController();
  String category = 'Identification';
  bool saving = false;
  @override
  void dispose() {
    details.dispose();
    source.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: const FloraText('Suggest a correction')),
    body: Form(
      key: form,
      child: ListView(
        padding: const EdgeInsets.all(24),
        children: [
          const Notice(
            'Reports are saved on this device only. A submission service is not connected; no report will be sent.',
          ),
          DropdownButtonFormField<String>(
            initialValue: category,
            decoration: const InputDecoration(labelText: 'Topic'),
            items:
                [
                      'Identification',
                      'Local knowledge',
                      'Plant care',
                      'Safety',
                      'Legal information',
                      'Other',
                    ]
                    .map((e) => DropdownMenuItem(value: e, child: FloraText(e)))
                    .toList(),
            onChanged: (v) => setState(() => category = v!),
          ),
          const SizedBox(height: 16),
          TextFormField(
            controller: details,
            maxLines: 5,
            maxLength: 2000,
            decoration: const InputDecoration(
              labelText: 'What should be corrected?',
            ),
            validator: (v) => (v?.trim().length ?? 0) < 10
                ? 'Please provide at least 10 characters.'
                : null,
          ),
          TextFormField(
            controller: source,
            maxLength: 500,
            decoration: const InputDecoration(
              labelText: 'Source or reference (optional)',
            ),
          ),
          const SizedBox(height: 20),
          FilledButton(
            onPressed: saving
                ? null
                : () async {
                    if (!form.currentState!.validate()) return;
                    setState(() => saving = true);
                    try {
                      await widget.store.saveReport({
                        'plantId': widget.plantId,
                        'topic': category,
                        'details': details.text.trim(),
                        'source': source.text.trim(),
                        'createdAt': DateTime.now().toIso8601String(),
                        'status': 'local-draft',
                      });
                      if (context.mounted) {
                        message(
                          context,
                          'Draft saved on this device. Not submitted.',
                        );
                        Navigator.pop(context);
                      }
                    } catch (_) {
                      if (context.mounted)
                        message(context, 'Draft could not be saved.');
                    } finally {
                      if (mounted) setState(() => saving = false);
                    }
                  },
            child: FloraText(saving ? 'Saving…' : 'Save report draft'),
          ),
        ],
      ),
    ),
  );
}

class PhotoCredits extends StatelessWidget {
  final String plantId;
  const PhotoCredits({super.key, required this.plantId});
  @override
  Widget build(BuildContext context) => FutureBuilder<String>(
    future: rootBundle.loadString('assets/photo_credits.json'),
    builder: (context, snapshot) {
      if (!snapshot.hasData) return const SizedBox.shrink();
      final item = (jsonDecode(snapshot.data!) as Map)[plantId] as Map?;
      if (item == null) return const SizedBox.shrink();
      return Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          FloraText('Photo: ${item['photographer']} · ${item['license']}'),
          FloraText(item['changes'] as String),
          SourceLink('Photograph source', item['source'] as String),
          SourceLink('Image reuse licence', item['license_url'] as String),
        ],
      );
    },
  );
}
