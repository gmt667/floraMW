import '../localization.dart';

import 'package:flutter/material.dart';

import '../models.dart';
import '../store.dart';
import '../ui.dart';
import 'profile.dart';

class GardenScreen extends StatelessWidget {
  final AppStore store;
  const GardenScreen({super.key, required this.store});
  @override
  Widget build(BuildContext context) => DefaultTabController(
    length: 2,
    child: Column(
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(24, 18, 24, 12),
          child: Align(
            alignment: Alignment.centerLeft,
            child: FloraText(
              store.tr('My garden', 'Munda wanga'),
              style: Theme.of(context).textTheme.headlineLarge,
            ),
          ),
        ),
        const TabBar(
          tabs: [
            Tab(text: 'Saved plants'),
            Tab(text: 'Discovery history'),
          ],
        ),
        Expanded(
          child: TabBarView(
            children: [
              ListView(
                padding: const EdgeInsets.all(20),
                children: [
                  const FloraText('Bookmarks are stored on this device.'),
                  const SizedBox(height: 12),
                  if (store.saved.isEmpty)
                    const EmptyState(
                      Icons.bookmarks_outlined,
                      'Room to grow',
                      'Save a plant from its profile to find it here.',
                    ),
                  ...plants
                      .where((p) => store.saved.contains(p.id))
                      .map(
                        (p) => PlantTile(
                          p,
                          onTap: () => Navigator.push(
                            context,
                            MaterialPageRoute<void>(
                              builder: (_) =>
                                  ProfileScreen(plant: p, store: store),
                            ),
                          ),
                          trailing: IconButton(
                            tooltip: 'Remove bookmark',
                            onPressed: () =>
                                guarded(context, () => store.toggleSave(p.id)),
                            icon: const Icon(Icons.bookmark_remove_outlined),
                          ),
                        ),
                      ),
                ],
              ),
              ListView(
                padding: const EdgeInsets.all(20),
                children: [
                  const Notice(
                    'All saved identifications are demonstrations, not verified botanical matches.',
                  ),
                  if (store.history.isEmpty)
                    const EmptyState(
                      Icons.history,
                      'No discoveries yet',
                      'Save a sample candidate from Identify to start a photo journal.',
                    ),
                  ...store.history.map((d) {
                    final p = plantById(d.plantId);
                    return Card(
                      elevation: 0,
                      child: ListTile(
                        leading: FloraText(
                          p.symbol,
                          style: const TextStyle(fontSize: 32),
                        ),
                        title: FloraText(p.name),
                        subtitle: FloraText(
                          '${d.createdAt.substring(0, 10)} · ${d.district ?? 'District not set'} · DEMO\n${d.note.isEmpty ? 'Add your field notes' : d.note}',
                          maxLines: 3,
                          overflow: TextOverflow.ellipsis,
                        ),
                        isThreeLine: true,
                        trailing: const Icon(Icons.chevron_right),
                        onTap: () => Navigator.push(
                          context,
                          MaterialPageRoute<void>(
                            builder: (_) =>
                                JournalScreen(store: store, discovery: d),
                          ),
                        ),
                      ),
                    );
                  }),
                ],
              ),
            ],
          ),
        ),
      ],
    ),
  );
}

class JournalScreen extends StatefulWidget {
  final AppStore store;
  final Discovery discovery;
  const JournalScreen({
    super.key,
    required this.store,
    required this.discovery,
  });
  @override
  State<JournalScreen> createState() => _JournalScreenState();
}

class _JournalScreenState extends State<JournalScreen> {
  late final note = TextEditingController(text: widget.discovery.note);
  @override
  void dispose() {
    note.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final p = plantById(widget.discovery.plantId);
    return Scaffold(
      appBar: AppBar(title: const FloraText('Field journal')),
      body: ListView(
        padding: const EdgeInsets.all(24),
        children: [
          if (widget.discovery.photo != null)
            PhotoView(widget.discovery.photo!)
          else
            PlantArt(p),
          const SizedBox(height: 20),
          FloraText(p.name, style: Theme.of(context).textTheme.headlineMedium),
          FloraText(
            '${widget.discovery.createdAt.substring(0, 10)} · ${widget.discovery.district ?? 'District not set'} · Demo identification',
          ),
          const SizedBox(height: 20),
          TextField(
            controller: note,
            maxLines: 6,
            maxLength: 2000,
            decoration: const InputDecoration(
              labelText: 'Your notes',
              hintText:
                  'What did you notice? Avoid sensitive personal details.',
            ),
          ),
          FilledButton(
            onPressed: () => guarded(context, () async {
              await widget.store.saveNote(widget.discovery, note.text.trim());
            }, success: 'Notes saved.'),
            child: const FloraText('Save notes'),
          ),
          OutlinedButton(
            onPressed: () => Navigator.push(
              context,
              MaterialPageRoute<void>(
                builder: (_) => ProfileScreen(plant: p, store: widget.store),
              ),
            ),
            child: const FloraText('Open plant profile'),
          ),
          TextButton.icon(
            onPressed: () async {
              if (!await confirm(
                context,
                'Delete discovery?',
                'The saved photo and notes will be removed from this device.',
              ))
                return;
              if (!context.mounted) return;
              await guarded(context, () async {
                await widget.store.removeDiscovery(widget.discovery);
                if (context.mounted) Navigator.pop(context);
              });
            },
            icon: const Icon(Icons.delete_outline),
            label: const FloraText('Delete discovery'),
          ),
        ],
      ),
    );
  }
}
