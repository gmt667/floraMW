import '../localization.dart';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:image_picker/image_picker.dart';

import '../models.dart';
import '../store.dart';
import '../ui.dart';
import 'profile.dart';

class IdentifyScreen extends StatefulWidget {
  final AppStore store;
  final IdentificationService service;
  const IdentifyScreen({super.key, required this.store, required this.service});
  @override
  State<IdentifyScreen> createState() => _IdentifyScreenState();
}

class _IdentifyScreenState extends State<IdentifyScreen> {
  String? path, error;
  bool busy = false;
  IdentificationResult? result;
  DemoOutcome outcome = DemoOutcome.matches;
  int generation = 0;
  final picker = ImagePicker();
  @override
  void initState() {
    super.initState();
    recover();
  }

  Future<void> recover() async {
    try {
      final r = await picker.retrieveLostData();
      if (!mounted) return;
      if (r.files?.isNotEmpty ?? false)
        setState(() => path = r.files!.first.path);
    } catch (_) {
      /* No pending image on unsupported platforms. */
    }
  }

  Future<void> pick(ImageSource source) async {
    final allowed = await confirm(
      context,
      source == ImageSource.camera ? 'Use camera?' : 'Choose a photo?',
      'FloraMW uses the device picker. Your selected photo stays on this device. No image or location is uploaded in this frontend demo.',
    );
    if (!allowed || !mounted) return;
    try {
      final file = await picker.pickImage(
        source: source,
        maxWidth: 1800,
        imageQuality: 85,
      );
      if (file != null && mounted)
        setState(() {
          path = file.path;
          error = null;
          result = null;
        });
    } on PlatformException catch (e) {
      if (mounted)
        setState(
          () => error =
              e.code.toLowerCase().contains('access') ||
                  e.code.toLowerCase().contains('denied')
              ? 'Permission denied. Allow camera or photo access in your device settings, then retry.'
              : 'The camera or gallery is unavailable. Try the other option.',
        );
    } catch (_) {
      if (mounted)
        setState(
          () => error = 'Could not open the photo. Choose another image.',
        );
    }
  }

  Future<void> identify() async {
    final request = ++generation;
    setState(() {
      busy = true;
      result = null;
      error = null;
    });
    try {
      final value = await widget.service.identify(path, outcome);
      if (mounted && request == generation) setState(() => result = value);
    } catch (_) {
      if (mounted && request == generation)
        setState(
          () => error = 'The demo request failed. Your photo is still available. Retry or choose a different demo outcome.',
        );
    } finally {
      if (mounted && request == generation) setState(() => busy = false);
    }
  }

  @override
  void dispose() {
    generation++;
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => ListView(
    padding: const EdgeInsets.all(24),
    children: [
      FloraText(
        widget.store.tr('What’s blooming?', 'Ndi duwa lanji?'),
        style: Theme.of(context).textTheme.headlineLarge,
      ),
      const SizedBox(height: 12),
      const FloraText(
        'Include the flower, leaves and whole plant. Use natural light and keep the image sharp.',
        style: TextStyle(height: 1.6),
      ),
      const SizedBox(height: 20),
      if (path != null)
        PhotoView(path!)
      else
        Container(
          height: 230,
          alignment: Alignment.center,
          decoration: BoxDecoration(
            color: const Color(0xffe4eadb),
            borderRadius: BorderRadius.circular(24),
          ),
          child: const Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(Icons.local_florist_outlined, size: 70, color: forest),
              SizedBox(height: 12),
              FloraText(
                'Your discovery starts here',
                style: TextStyle(color: forest),
              ),
            ],
          ),
        ),
      const SizedBox(height: 16),
      FilledButton.icon(
        onPressed: busy ? null : () => pick(ImageSource.camera),
        icon: const Icon(Icons.camera_alt_outlined),
        label: FloraText(
          widget.store.tr('Take a photo', 'Jambulani chithunzi'),
        ),
      ),
      OutlinedButton.icon(
        onPressed: busy ? null : () => pick(ImageSource.gallery),
        icon: const Icon(Icons.photo_library_outlined),
        label: FloraText(
          widget.store.tr('Choose from gallery', 'Sankhani chithunzi'),
        ),
      ),
      if (path != null)
        TextButton(
          onPressed: busy
              ? null
              : () => setState(() {
                  path = null;
                  result = null;
                  error = null;
                }),
          child: const FloraText('Remove photo'),
        ),
      const Notice(
        'DEMO MODE · No AI is connected. Sample candidates do not depend on your photo. No confidence percentages are fabricated.',
      ),
      DropdownButtonFormField<DemoOutcome>(
        value: outcome,
        decoration: const InputDecoration(labelText: 'Preview result state'),
        items: const [
          DropdownMenuItem(
            value: DemoOutcome.matches,
            child: FloraText('Sample candidates'),
          ),
          DropdownMenuItem(
            value: DemoOutcome.noMatch,
            child: FloraText('No match'),
          ),
          DropdownMenuItem(
            value: DemoOutcome.error,
            child: FloraText('Service error'),
          ),
        ],
        onChanged: busy ? null : (v) => setState(() => outcome = v!),
      ),
      const SizedBox(height: 14),
      FilledButton.icon(
        onPressed: busy ? null : identify,
        icon: const Icon(Icons.auto_awesome_outlined),
        label: FloraText(
          path == null
              ? 'Explore demo without a photo'
              : 'Run demo identification',
        ),
      ),
      if (busy) ...[
        const SizedBox(height: 24),
        const LinearProgressIndicator(),
        const SizedBox(height: 12),
        const FloraText('Preparing a demonstration result…'),
        TextButton(
          onPressed: () {
            generation++;
            setState(() => busy = false);
          },
          child: const FloraText('Cancel'),
        ),
      ],
      if (error != null) ...[
        Notice(error!, icon: Icons.error_outline),
        TextButton(
          onPressed: busy ? null : identify,
          child: const FloraText('Retry demo request'),
        ),
      ],
      if (result != null && result!.candidateIds.isEmpty)
        EmptyState(
          Icons.search_off,
          'No match found',
          'This is the demo no-match state. Try a clearer view of the flower and leaves.',
          action: OutlinedButton(
            onPressed: () => pick(ImageSource.camera),
            child: const FloraText('Retake photo'),
          ),
        ),
      if (result != null && result!.candidateIds.isNotEmpty) ...[
        const SizedBox(height: 24),
        FloraText(
          'Sample candidates',
          style: Theme.of(context).textTheme.titleLarge,
        ),
        const FloraText(
          'Compare features with a botanist. These are not image predictions.',
        ),
        ...result!.candidateIds.map((id) {
          final p = plantById(id);
          return Column(
            children: [
              PlantTile(
                p,
                onTap: () => Navigator.push(
                  context,
                  MaterialPageRoute<void>(
                    builder: (_) =>
                        ProfileScreen(plant: p, store: widget.store),
                  ),
                ),
              ),
              TextButton.icon(
                onPressed: () => guarded(
                  context,
                  () => widget.store.addDiscovery(p.id, path),
                  success: 'Demo discovery saved with your photo.',
                ),
                icon: const Icon(Icons.add_circle_outline),
                label: FloraText('Save ${p.name} as demo discovery'),
              ),
            ],
          );
        }),
      ],
      const SizedBox(height: 24),
    ],
  );
}
