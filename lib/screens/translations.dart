import 'package:flutter/material.dart';
import '../localization.dart';
import '../locale_data.dart';
import '../store.dart';
import '../ui.dart';

class TranslationScreen extends StatefulWidget {
  final AppStore store;
  const TranslationScreen({super.key, required this.store});
  @override
  State<TranslationScreen> createState() => _TranslationScreenState();
}

class _TranslationScreenState extends State<TranslationScreen> {
  late String language = widget.store.language == 'en'
      ? 'ny'
      : widget.store.language;
  String query = '';
  bool missingOnly = false;
  Map get bundled =>
      (TranslationCatalog.packs[language] as Map?)?['strings'] as Map? ?? {};
  Map<String, String> get local =>
      widget.store.translationOverrides[language] ?? {};
  List<String> get keys =>
      ((TranslationCatalog.packs['en'] as Map?)?['strings'] as Map? ?? {}).keys
          .cast<String>()
          .toList()
        ..sort();
  bool translated(String key) =>
      local[key]?.isNotEmpty == true || bundled[key] != null;
  Future<void> edit(String key) async {
    final control = TextEditingController(
      text: local[key] ?? bundled[key] as String? ?? '',
    );
    final value = await showDialog<String>(
      context: context,
      builder: (c) => AlertDialog(
        title: FloraText(languageNames[language]!),
        content: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const FloraText('English source'),
              const SizedBox(height: 8),
              Text(key),
              const SizedBox(height: 16),
              TextField(
                controller: control,
                maxLines: 4,
                maxLength: 2000,
                decoration: const InputDecoration(
                  labelText: 'Local translation',
                  helperText: 'Leave empty to remove your local edit.',
                ),
              ),
            ],
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(c),
            child: const FloraText('Cancel'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(c, control.text),
            child: const FloraText('Save local translation'),
          ),
        ],
      ),
    );
    // Dialog exit animation may still use the controller, so dispose next frame.
    WidgetsBinding.instance.addPostFrameCallback((_) => control.dispose());
    if (value != null && mounted)
      await guarded(
        context,
        () => widget.store.setTranslation(language, key, value),
        success:
            'Local translation saved. Native-speaker review is still required.',
      );
  }

  @override
  Widget build(BuildContext context) => ListenableBuilder(
    listenable: widget.store,
    builder: (context, _) {
      final all = keys;
      final count = all.where(translated).length;
      final visible = all
          .where(
            (k) =>
                k.toLowerCase().contains(query.toLowerCase()) &&
                (!missingOnly || !translated(k)),
          )
          .toList();
      return Scaffold(
        appBar: AppBar(title: const FloraText('Language review')),
        body: ListView(
          children: [
            Padding(
              padding: const EdgeInsets.all(20),
              child: Column(
                children: [
                  DropdownButtonFormField<String>(
                    initialValue: language,
                    isExpanded: true,
                    decoration: const InputDecoration(
                      labelText: 'Language to review',
                    ),
                    items: languageNames.entries
                        .where((e) => e.key != 'en')
                        .map(
                          (e) => DropdownMenuItem(
                            value: e.key,
                            child: Text(e.value),
                          ),
                        )
                        .toList(),
                    onChanged: (v) => setState(() => language = v!),
                  ),
                  const SizedBox(height: 12),
                  FloraText(
                    '$count / ${all.length} interface phrases have wording. Coverage is not a measure of translation accuracy.',
                  ),
                  const Notice(
                    'All non-English packs need native-speaker review. Local edits stay on this device and are not submitted. Botanical and safety prose must be reviewed separately.',
                  ),
                  TextField(
                    decoration: const InputDecoration(
                      labelText: 'Find an English phrase',
                      prefixIcon: Icon(Icons.search),
                    ),
                    onChanged: (v) => setState(() => query = v),
                  ),
                  SwitchListTile(
                    contentPadding: EdgeInsets.zero,
                    title: const FloraText('Show missing translations only'),
                    value: missingOnly,
                    onChanged: (v) => setState(() => missingOnly = v),
                  ),
                ],
              ),
            ),
            ...visible.map(
              (k) => Padding(
                padding: const EdgeInsets.symmetric(horizontal: 20),
                child: Card(
                  child: ListTile(
                    title: Text(k),
                    subtitle: Text(
                      local[k] ??
                          bundled[k] as String? ??
                          'English fallback · wording needed',
                    ),
                    trailing: const Icon(Icons.edit_outlined),
                    onTap: () => edit(k),
                  ),
                ),
              ),
            ),
            const SizedBox(height: 24),
          ],
        ),
      );
    },
  );
}
