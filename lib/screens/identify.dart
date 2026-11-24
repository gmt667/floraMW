import '../localization.dart';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:image_picker/image_picker.dart';

import '../models.dart';
import '../services/api_client.dart';
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
      'Choosing a photo does not upload it. FloraMW will ask for your permission before sending the image securely to its identification service.',
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
    if (path == null) {
      setState(
        () => error =
            'Choose a flower photo before requesting identification.',
      );
      return;
    }
    final allowed = await confirm(
      context,
      'Send photo for identification?',
      'Your selected flower photo will be uploaded to the FloraMW backend and forwarded to its configured identification provider. The backend processes the image for this request; the app does not promise permanent storage or deletion beyond the provider and server policies. Do not upload people, private documents or sensitive images. Continue?',
    );
    if (!allowed || !mounted) return;
    final request = ++generation;
    setState(() {
      busy = true;
      result = null;
      error = null;
    });
    try {
      final value = await widget.service.identify(path, DemoOutcome.matches);
      if (mounted && request == generation) {
        setState(() => result = value);
      }
    } catch (exception) {
      if (mounted && request == generation) {
        final message = _errorMessageFor(exception);
        setState(() => error = message);
      }
    } finally {
      if (mounted && request == generation) {
        setState(() => busy = false);
      }
    }
  }

  String _errorMessageFor(Object exception) {
    if (exception is FloraApiException) return exception.message;
    return 'FloraMW could not identify this photo. Check your internet connection '
        'and try again.';
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
        'Identification requires an internet connection. Results are suggestions, not confirmed species identifications.',
      ),
      const SizedBox(height: 14),
      FilledButton.icon(
        onPressed: busy || path == null ? null : identify,
        icon: const Icon(Icons.auto_awesome_outlined),
        label: const FloraText('Identify this flower'),
      ),
      if (busy) ...[
        const SizedBox(height: 24),
        const LinearProgressIndicator(),
        const SizedBox(height: 12),
        const FloraText(
          'Sending photo securely and checking possible matches…',
        ),
      ],
      if (error != null) ...[
        Notice(error!, icon: Icons.error_outline),
        TextButton(
          onPressed: busy ? null : identify,
          child: const FloraText('Retry identification'),
        ),
      ],
      if (result != null) Notice(result!.safetyDisclaimer),
      if (result != null && result!.candidateIds.isEmpty)
        EmptyState(
          Icons.search_off,
          'No match found',
          'The service did not return a reliable catalogue match. Try a clearer photo showing the flower and leaves.',
          action: OutlinedButton(
            onPressed: () => pick(ImageSource.camera),
            child: const FloraText('Retake photo'),
          ),
        ),
      if (result != null && result!.candidateIds.isNotEmpty) ...[
        const SizedBox(height: 24),
        FloraText(
          result!.isDemo ? 'Demonstration candidates' : 'Possible matches',
          style: Theme.of(context).textTheme.titleLarge,
        ),
        Notice(
          result!.isDemo
              ? 'The backend is currently using a demonstration provider (${result!.providerId}). These candidates are examples and are not based on your photograph.'
              : 'These are possible matches returned by ${result!.providerId}. They are not confirmed identifications.',
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
                  () => widget.store.addDiscovery(
                    p.id,
                    path,
                    isDemo: result!.isDemo,
                  ),
                  success: result!.isDemo
                      ? 'Demonstration discovery saved with your photo.'
                      : 'Possible match saved to your field journal.',
                ),
                icon: const Icon(Icons.add_circle_outline),
                label: FloraText(
                  result!.isDemo
                      ? 'Save ${p.name} as demo discovery'
                      : 'Save ${p.name} to field journal',
                ),
              ),
            ],
          );
        }),
      ],
      const SizedBox(height: 24),
    ],
  );
}
