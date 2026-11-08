import 'localization.dart';

import 'package:flutter/material.dart';

import 'locale_data.dart';
import 'store.dart';
import 'ui.dart';

class DistrictSelector extends StatelessWidget {
  final String? value;
  final ValueChanged<String> onChanged;
  const DistrictSelector({
    super.key,
    required this.value,
    required this.onChanged,
  });
  @override
  Widget build(BuildContext context) => OutlinedButton.icon(
    onPressed: () async {
      final selected = await Navigator.push<String>(
        context,
        MaterialPageRoute(builder: (_) => DistrictPicker(selected: value)),
      );
      if (selected != null) onChanged(selected);
    },
    icon: const Icon(Icons.location_on_outlined),
    label: FloraText(value ?? 'Choose your district'),
  );
}

class DistrictPicker extends StatefulWidget {
  final String? selected;
  const DistrictPicker({super.key, this.selected});
  @override
  State<DistrictPicker> createState() => _DistrictPickerState();
}

class _DistrictPickerState extends State<DistrictPicker> {
  String query = '';
  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: const FloraText('Your district')),
    body: Column(
      children: [
        Padding(
          padding: const EdgeInsets.all(20),
          child: TextField(
            autofocus: true,
            decoration: const InputDecoration(
              labelText: 'Search all 28 districts',
              prefixIcon: Icon(Icons.search),
            ),
            onChanged: (v) => setState(() => query = v),
          ),
        ),
        Expanded(
          child: ListView(
            children: [
              for (final region in districtsByRegion.entries) ...[
                if (region.value.any(
                  (d) => d.toLowerCase().contains(query.toLowerCase()),
                ))
                  Padding(
                    padding: const EdgeInsets.fromLTRB(24, 16, 24, 8),
                    child: FloraText(
                      '${region.key} Region',
                      style: Theme.of(context).textTheme.titleMedium,
                    ),
                  ),
                ...region.value
                    .where((d) => d.toLowerCase().contains(query.toLowerCase()))
                    .map(
                      (d) => ListTile(
                        title: FloraText(d),
                        trailing: widget.selected == d
                            ? const Icon(Icons.check_circle)
                            : null,
                        onTap: () => Navigator.pop(context, d),
                      ),
                    ),
              ],
              if (!allDistricts.any(
                (d) => d.toLowerCase().contains(query.toLowerCase()),
              ))
                const EmptyState(
                  Icons.search_off,
                  'District not found',
                  'Try another spelling. All 28 districts are listed.',
                ),
            ],
          ),
        ),
      ],
    ),
  );
}

class SetupScreen extends StatefulWidget {
  final AppStore store;
  const SetupScreen({super.key, required this.store});
  @override
  State<SetupScreen> createState() => _SetupScreenState();
}

class _SetupScreenState extends State<SetupScreen> {
  late String? district = widget.store.district;
  late String language = widget.store.language;
  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: const FloraText('Make FloraMW yours')),
    body: ListView(
      padding: const EdgeInsets.all(24),
      children: [
        const Icon(Icons.map_outlined, size: 72, color: forest),
        const SizedBox(height: 24),
        FloraText(
          'Which district are you in?',
          style: Theme.of(context).textTheme.headlineMedium,
        ),
        const SizedBox(height: 12),
        const FloraText(
          'Select your district to add context to your field journal. Your choice stays on this device; GPS is not requested.',
        ),
        const SizedBox(height: 20),
        DistrictSelector(
          value: district,
          onChanged: (v) => setState(() => district = v),
        ),
        const SizedBox(height: 24),
        DropdownButtonFormField<String>(
          initialValue: language,
          isExpanded: true,
          decoration: const InputDecoration(labelText: 'Preferred language'),
          items: languageNames.entries
              .map(
                (e) =>
                    DropdownMenuItem(value: e.key, child: FloraText(e.value)),
              )
              .toList(),
          onChanged: (v) => setState(() => language = v!),
        ),
        const SizedBox(height: 16),
        const Notice(
          'Language packs are under review. Chichewa includes draft navigation. Untranslated text appears in English with a visible fallback notice; selecting a language does not imply a complete translation.',
        ),
        const SizedBox(height: 24),
        FilledButton(
          onPressed: district == null
              ? null
              : () {
                  widget.store.district = district;
                  widget.store.language = language;
                  Navigator.pop(context, true);
                },
          child: const FloraText('Save preferences & explore'),
        ),
      ],
    ),
  );
}
