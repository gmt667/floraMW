import '../localization.dart';

import 'package:flutter/material.dart';

import '../store.dart';
import '../locale_data.dart';
import '../preferences.dart';
import 'translations.dart';
import '../ui.dart';
import 'profile.dart';

class SettingsScreen extends StatelessWidget {
  final AppStore store;
  final VoidCallback replayWelcome;
  const SettingsScreen({
    super.key,
    required this.store,
    required this.replayWelcome,
  });
  @override
  Widget build(BuildContext context) => ListView(
    padding: const EdgeInsets.all(24),
    children: [
      FloraText(
        store.tr('Settings', 'Zokonda'),
        style: Theme.of(context).textTheme.headlineLarge,
      ),
      const SizedBox(height: 20),
      const Notice(
        'Offline-ready frontend · the sample catalogue and saved records work without internet. Live AI and cloud sync are not connected.',
      ),
      DropdownButtonFormField<String>(
        initialValue: store.language,
        isExpanded: true,
        decoration: const InputDecoration(labelText: 'Preferred language'),
        items: languageNames.entries
            .map(
              (e) => DropdownMenuItem(value: e.key, child: FloraText(e.value)),
            )
            .toList(),
        onChanged: (v) => guarded(context, () async {
          store.language = v!;
          await store.commit();
        }),
      ),
      const SizedBox(height: 12),
      DistrictSelector(
        value: store.district,
        onChanged: (v) => guarded(context, () async {
          store.district = v;
          await store.commit();
        }),
      ),
      const Padding(
        padding: EdgeInsets.only(top: 8, bottom: 16),
        child: FloraText(
          'Chichewa, Yao, Tumbuka, Sena, Lhomwe and Tonga are selectable. Language packs need native-speaker review. Untranslated text appears in English; Chichewa includes draft navigation.',
          style: TextStyle(fontSize: 12),
        ),
      ),
      SwitchListTile(
        contentPadding: EdgeInsets.zero,
        title: const FloraText('Dark appearance'),
        value: store.dark,
        onChanged: (v) => guarded(context, () async {
          store.dark = v;
          await store.commit();
        }),
      ),
      SwitchListTile(
        contentPadding: EdgeInsets.zero,
        title: const FloraText('Larger text'),
        subtitle: const FloraText('Also respects your device text size'),
        value: store.largeText,
        onChanged: (v) => guarded(context, () async {
          store.largeText = v;
          await store.commit();
        }),
      ),
      ListTile(
        contentPadding: EdgeInsets.zero,
        leading: const Icon(Icons.translate),
        title: const FloraText('Language packs & translation review'),
        subtitle: const FloraText('Review coverage and save local wording'),
        onTap: () => Navigator.push(
          context,
          MaterialPageRoute<void>(
            builder: (_) => TranslationScreen(store: store),
          ),
        ),
      ),
      const Divider(),
      ListTile(
        contentPadding: EdgeInsets.zero,
        leading: const Icon(Icons.privacy_tip_outlined),
        title: const FloraText('Privacy & photo handling'),
        trailing: const Icon(Icons.chevron_right),
        onTap: () => info(
          context,
          'Privacy & photo handling',
          'FloraMW stores preferences, bookmarks, journal notes and report drafts locally. Photos are copied into app-private storage only when you save a discovery. Camera/gallery selections can also exist in operating-system caches. This frontend sends no photos, location or notes to a server and includes no advertising or analytics. Device backups may include app data according to your operating-system settings. Deleting a discovery removes its app-owned photo; it does not remove your original gallery photo. Clear local records below to delete saved discoveries, bookmarks, draft reports and local translation edits. External reference links open your browser and are subject to the source website’s privacy practices. Uninstalling and backup restoration follow your device policies. A real AI service must explain its retention and request upload consent before activation.',
        ),
      ),
      ListTile(
        contentPadding: EdgeInsets.zero,
        leading: const Icon(Icons.help_outline),
        title: const FloraText('Photo tips & help'),
        onTap: () => info(
          context,
          'Getting a useful photo',
          'Use daylight, a steady camera and an uncluttered background. Include flowers, leaves and the whole plant in separate views where possible. Avoid touching or tasting an unknown plant. If access is denied, enable camera/photo permission in device settings. No-match and service-error states can be explored from Identify. Saved sample results remain demo records.',
        ),
      ),
      ListTile(
        contentPadding: EdgeInsets.zero,
        leading: const Icon(Icons.flag_outlined),
        title: const FloraText('Feedback & correction drafts'),
        subtitle: FloraText(
          '${store.reports.length} local drafts · none submitted',
        ),
        onTap: () => Navigator.push(
          context,
          MaterialPageRoute<void>(builder: (_) => DraftsScreen(store: store)),
        ),
      ),
      ListTile(
        contentPadding: EdgeInsets.zero,
        leading: const Icon(Icons.replay),
        title: const FloraText('Replay introduction'),
        onTap: replayWelcome,
      ),
      ListTile(
        contentPadding: EdgeInsets.zero,
        leading: const Icon(Icons.info_outline),
        title: const FloraText('About FloraMW'),
        onTap: () => info(
          context,
          'FloraMW',
          'A Malawi-focused botanical companion. Version 1.0.0 frontend demonstration. Built with Flutter and Dart for Android and iOS. Reference photographs include attribution and reuse licences. No live AI or personalized treatment advice is included. General botanical summaries link to sources; local traditional uses and district occurrence await review.',
        ),
      ),
      ListTile(
        contentPadding: EdgeInsets.zero,
        leading: const Icon(Icons.description_outlined),
        title: const FloraText('Open-source licences'),
        onTap: () => showLicensePage(
          context: context,
          applicationName: 'FloraMW',
          applicationVersion: '1.0.0',
        ),
      ),
      const SizedBox(height: 12),
      OutlinedButton.icon(
        onPressed: () async {
          if (!await confirm(
            context,
            'Clear all local records?',
            'Delete bookmarks, discovery photos, notes and report drafts. Appearance, district and language preferences will remain. Your local translation edits will also be deleted.',
          ))
            return;
          if (context.mounted)
            await guarded(
              context,
              store.clearPersonalData,
              success: 'Local records deleted.',
            );
        },
        icon: const Icon(Icons.delete_sweep_outlined),
        label: const FloraText('Clear local records'),
      ),
      const SizedBox(height: 20),
      const Center(child: FloraText('FloraMW · Knowledge grows with care.')),
    ],
  );
  void info(BuildContext context, String title, String body) => Navigator.push(
    context,
    MaterialPageRoute<void>(
      builder: (_) => Scaffold(
        appBar: AppBar(title: FloraText(title)),
        body: ListView(
          padding: const EdgeInsets.all(24),
          children: [
            FloraText(body, style: const TextStyle(height: 1.7, fontSize: 16)),
          ],
        ),
      ),
    ),
  );
}

class DraftsScreen extends StatefulWidget {
  final AppStore store;
  const DraftsScreen({super.key, required this.store});
  @override
  State<DraftsScreen> createState() => _DraftsScreenState();
}

class _DraftsScreenState extends State<DraftsScreen> {
  @override
  Widget build(BuildContext context) => ListenableBuilder(
    listenable: widget.store,
    builder: (context, _) => Scaffold(
      appBar: AppBar(title: const FloraText('Correction drafts')),
      floatingActionButton: FloatingActionButton.extended(
        onPressed: () => Navigator.push(
          context,
          MaterialPageRoute<void>(
            builder: (_) => ReportScreen(store: widget.store),
          ),
        ),
        icon: const Icon(Icons.add),
        label: const FloraText('New draft'),
      ),
      body: ListView(
        padding: const EdgeInsets.fromLTRB(20, 20, 20, 100),
        children: [
          const Notice(
            'Drafts stay on this device. Nothing has been submitted.',
          ),
          if (widget.store.reports.isEmpty)
            const EmptyState(
              Icons.drafts_outlined,
              'No drafts',
              'Create a correction draft or report from a plant profile.',
            ),
          ...widget.store.reports.map(
            (r) => Card(
              child: ListTile(
                title: FloraText(r['topic'] as String),
                subtitle: FloraText(
                  '${r['details']}\nSource: ${r['source']}\nStatus: local draft',
                ),
                trailing: IconButton(
                  tooltip: 'Delete draft',
                  icon: const Icon(Icons.delete_outline),
                  onPressed: () async {
                    if (!await confirm(
                      context,
                      'Delete draft?',
                      'This local report will be removed.',
                    ))
                      return;
                    if (context.mounted)
                      await guarded(context, () async {
                        widget.store.reports.remove(r);
                        await widget.store.commit();
                      });
                  },
                ),
              ),
            ),
          ),
        ],
      ),
    ),
  );
}
