import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:path_provider/path_provider.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'models.dart';
import 'locale_data.dart';

class AppStore extends ChangeNotifier {
  final SharedPreferences prefs;
  AppStore(this.prefs) {
    try {
      final raw = prefs.getString('floramw_state');
      final j = raw == null
          ? <String, dynamic>{}
          : Map<String, dynamic>.from(jsonDecode(raw) as Map);
      onboarding =
          j['onboarding'] as bool? ?? prefs.getBool('onboarding') ?? false;
      district = j['district'] as String?;
      language = j['language'] as String? ?? 'en';
      if (!languageNames.containsKey(language)) language = 'en';
      if (district != null && !allDistricts.contains(district)) district = null;
      dark = j['dark'] as bool? ?? false;
      largeText = j['largeText'] as bool? ?? false;
      saved.addAll(
        (j['saved'] as List? ?? []).cast<String>().where(
          (id) => plants.any((p) => p.id == id),
        ),
      );
      history.addAll(
        (j['history'] as List? ?? []).map(
          (e) => Discovery.fromJson(Map<String, dynamic>.from(e as Map)),
        ),
      );
      reports.addAll(
        (j['reports'] as List? ?? []).map(
          (e) => Map<String, dynamic>.from(e as Map),
        ),
      );
    } catch (_) {
      loadWarning = 'Some local records could not be read. Avoid saving changes until you have checked your device storage.';
    }
  }
  bool onboarding = false, dark = false, largeText = false;
  String language = 'en';
  String? district, loadWarning;
  final Set<String> saved = {};
  final List<Discovery> history = [];
  final List<Map<String, dynamic>> reports = [];
  String tr(String en, String ny) => localized(language, en);
  Future<void> commit() async {
    final state = jsonEncode({
      'onboarding': onboarding,
      'district': district,
      'language': language,
      'dark': dark,
      'largeText': largeText,
      'saved': saved.toList(),
      'history': history.map((d) => d.toJson()).toList(),
      'reports': reports,
    });
    if (!await prefs.setString('floramw_state', state))
      throw Exception('Device storage could not save changes.');
    notifyListeners();
  }

  Future<void> toggleSave(String id) async {
    final existed = saved.contains(id);
    existed ? saved.remove(id) : saved.add(id);
    try {
      await commit();
    } catch (_) {
      existed ? saved.add(id) : saved.remove(id);
      notifyListeners();
      rethrow;
    }
  }

  Future<void> addDiscovery(String plantId, String? path) async {
    final id = DateTime.now().microsecondsSinceEpoch.toString();
    String? durable;
    if (path != null) {
      final dir = await getApplicationDocumentsDirectory();
      durable = '${dir.path}/floramw_$id.jpg';
      await File(path).copy(durable);
    }
    final record = Discovery(
      id: id,
      plantId: plantId,
      createdAt: DateTime.now().toIso8601String(),
      photo: durable,
      district: district,
    );
    history.insert(0, record);
    try {
      await commit();
    } catch (_) {
      history.remove(record);
      if (durable != null) {
        final file = File(durable);
        if (await file.exists()) await file.delete();
      }
      notifyListeners();
      rethrow;
    }
  }

  Future<void> saveNote(Discovery d, String note) async {
    final previous = d.note;
    d.note = note;
    try {
      await commit();
    } catch (_) {
      d.note = previous;
      rethrow;
    }
  }

  Future<void> saveReport(Map<String, dynamic> report) async {
    reports.add(report);
    try {
      await commit();
    } catch (_) {
      reports.remove(report);
      rethrow;
    }
  }

  Future<void> removeDiscovery(Discovery d) async {
    final index = history.indexOf(d);
    history.remove(d);
    try {
      await commit();
    } catch (_) {
      history.insert(index < 0 ? 0 : index, d);
      notifyListeners();
      rethrow;
    }
    if (d.photo != null) {
      final file = File(d.photo!);
      if (await file.exists()) await file.delete();
    }
  }

  Future<void> clearPersonalData() async {
    final oldHistory = List<Discovery>.from(history);
    final oldSaved = Set<String>.from(saved);
    final oldReports = List<Map<String, dynamic>>.from(reports);
    history.clear();
    saved.clear();
    reports.clear();
    try {
      await commit();
    } catch (_) {
      history.addAll(oldHistory);
      saved.addAll(oldSaved);
      reports.addAll(oldReports);
      notifyListeners();
      rethrow;
    }
    if (!oldHistory.any((d) => d.photo != null)) return;
    final dir = await getApplicationDocumentsDirectory();
    await for (final entity in dir.list()) {
      if (entity is File && entity.path.split('/').last.startsWith('floramw_'))
        await entity.delete();
    }
  }
}
