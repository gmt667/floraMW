import 'dart:convert';

import 'package:flutter/services.dart';

import '../localization.dart';

import 'package:flutter/material.dart';

import '../models.dart';
import '../services/api_client.dart';
import '../store.dart';
import '../ui.dart';

class ProfileScreen extends StatefulWidget {
  final Plant plant;
  final AppStore store;
  const ProfileScreen({super.key, required this.plant, required this.store});
  @override
  State<ProfileScreen> createState() => _ProfileScreenState();
}

class _ProfileScreenState extends State<ProfileScreen> {
  late final Future<Plant?> _remoteProfile = _loadRemoteProfile();

  Future<Plant?> _loadRemoteProfile() async {
    try {
      final client = widget.store.syncService?.client ??
          FloraApiClient(prefs: widget.store.prefs);
      return await client.getFlower(widget.plant.id);
    } catch (_) {
      return null;
    }
  }

  @override
  Widget build(BuildContext context) => FutureBuilder<Plant?>(
    future: _remoteProfile,
    builder: (context, snapshot) {
      final profilePlant = snapshot.data ?? widget.plant;
      return ListenableBuilder(
    listenable: widget.store,
    builder: (context, _) => Scaffold(
      appBar: AppBar(
        title: const FloraText('Flower profile'),
        actions: [
          IconButton(
            tooltip: widget.store.saved.contains(profilePlant.id)
                ? 'Remove bookmark'
                : 'Save plant',
            onPressed: () => guarded(context, () => widget.store.toggleSave(profilePlant.id)),
            icon: Icon(
              widget.store.saved.contains(profilePlant.id)
                  ? Icons.bookmark
                  : Icons.bookmark_outline,
            ),
          ),
        ],
      ),
      body: ListView(
        padding: const EdgeInsets.all(24),
        children: [
          PlantArt(profilePlant),
          const SizedBox(height: 20),
          const FloraText(
            'REFERENCE PROFILE · NOT A PHOTO MATCH',
            style: TextStyle(fontSize: 11, letterSpacing: 1.5),
          ),
          const SizedBox(height: 12),
          FloraText(
            profilePlant.name,
            style: Theme.of(context).textTheme.headlineLarge,
          ),
          FloraText(
            profilePlant.scientific,
            style: const TextStyle(fontStyle: FontStyle.italic, fontSize: 16),
          ),
          Wrap(
            spacing: 8,
            children: [
              Chip(label: FloraText(profilePlant.family)),
              Chip(label: FloraText(profilePlant.category)),
            ],
          ),
          FloraText(profilePlant.description, style: const TextStyle(height: 1.6)),
          const SizedBox(height: 12),
          const Notice(
            'This reference profile is not a confirmed match for your photo. General summaries link to public sources; local knowledge and Malawi distribution still need field review.',
          ),
          ...profilePlant.sections.entries.map(
            (e) => Card(
              elevation: 0,
              child: ExpansionTile(
                title: FloraText(
                  e.key == 'Identifying features' ? 'Flower features' : e.key,
                ),
                subtitle: FloraText(
                  [
                        'Local names & knowledge',
                        'Malawi distribution',
                      ].contains(e.key)
                      ? 'Local verification pending'
                      : e.key == 'Medicinal research' &&
                            profilePlant.id != 'periwinkle'
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
          ...profilePlant.sources.map((s) => SourceLink(s.title, s.url)),
          PhotoCredits(plantId: profilePlant.id),
          const SizedBox(height: 12),
          OutlinedButton.icon(
            onPressed: () => Navigator.push(
              context,
              MaterialPageRoute<void>(
                builder: (_) => ReportScreen(store: widget.store, plantId: profilePlant.id),
              ),
            ),
            icon: const Icon(Icons.flag_outlined),
            label: const FloraText('Suggest a correction'),
          ),
        ],
      ),
    ),
  );
    },
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
  bool submitting = false;

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
            'Suggest a botanical correction for herbarium review, or save a local draft on this device.',
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
            onPressed: (saving || submitting)
                ? null
                : () async {
                    if (!form.currentState!.validate()) return;
                    setState(() => submitting = true);
                    final client =
                        widget.store.syncService?.client ??
                        FloraApiClient(prefs: widget.store.prefs);
                    try {
                      final result = await client.submitReport(
                        flowerId: widget.plantId,
                        plantId: widget.plantId,
                        topic: category,
                        details: details.text.trim(),
                        source: source.text.trim(),
                      );
                      await widget.store.saveReport({
                        'id': result['id'],
                        'plantId': widget.plantId,
                        'topic': category,
                        'details': details.text.trim(),
                        'source': source.text.trim(),
                        'createdAt':
                            result['created_at'] ??
                            DateTime.now().toIso8601String(),
                        'status': 'submitted',
                      });
                      if (context.mounted) {
                        message(context, 'Report submitted successfully.');
                        Navigator.pop(context);
                      }
                    } catch (_) {
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
                          'Submission failed. Saved as local draft.',
                        );
                      }
                    } finally {
                      if (mounted) setState(() => submitting = false);
                    }
                  },
            child: FloraText(submitting ? 'Submitting…' : 'Submit report'),
          ),
          const SizedBox(height: 12),
          OutlinedButton(
            onPressed: (saving || submitting)
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
