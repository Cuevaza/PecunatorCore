import 'dart:convert';

import 'package:http/http.dart' as http;

class ApiException implements Exception {
  final String message;
  ApiException(this.message);

  @override
  String toString() => message;
}

class EngineApi {
  EngineApi(this.baseUrl);
  final String baseUrl;

  Uri _u(String path) => Uri.parse('$baseUrl$path');

  Future<Map<String, dynamic>> health() async {
    final r = await http.get(_u('/health'));
    _ensure(r);
    return _jsonMap(r.body);
  }

  Future<Map<String, dynamic>> vaultStatus() async {
    final r = await http.get(_u('/api/v1/vault/status'));
    _ensure(r);
    return _jsonMap(r.body);
  }

  Future<Map<String, dynamic>> unlockVault(String masterPassword) async {
    final r = await http.post(
      _u('/api/v1/vault/session'),
      headers: {'Content-Type': 'application/json'},
      body: jsonEncode({'master_password': masterPassword}),
    );
    _ensure(r);
    return _jsonMap(r.body);
  }

  Future<Map<String, dynamic>> botConfig() async {
    final r = await http.get(_u('/api/v1/bot/config'));
    _ensure(r);
    return _jsonMap(r.body);
  }

  Future<Map<String, dynamic>> setBotConfig(Map<String, dynamic> body) async {
    final r = await http.put(
      _u('/api/v1/bot/config'),
      headers: {'Content-Type': 'application/json'},
      body: jsonEncode(body),
    );
    _ensure(r);
    return _jsonMap(r.body);
  }

  Future<Map<String, dynamic>> botStatus() async {
    final r = await http.get(_u('/api/v1/bot/status'));
    _ensure(r);
    return _jsonMap(r.body);
  }

  Future<Map<String, dynamic>> botStart({String? masterPassword}) async {
    final r = await http.post(
      _u('/api/v1/bot/start'),
      headers: {'Content-Type': 'application/json'},
      body: jsonEncode({'master_password': masterPassword}),
    );
    _ensure(r);
    return _jsonMap(r.body);
  }

  Future<Map<String, dynamic>> botStop() async {
    final r = await http.post(_u('/api/v1/bot/stop'));
    _ensure(r);
    return _jsonMap(r.body);
  }

  Future<Map<String, dynamic>> botRunOnce({String? masterPassword}) async {
    final r = await http.post(
      _u('/api/v1/bot/run_once'),
      headers: {'Content-Type': 'application/json'},
      body: jsonEncode({'master_password': masterPassword}),
    );
    _ensure(r);
    return _jsonMap(r.body);
  }

  Future<Map<String, dynamic>> gatewayStart({String? masterPassword}) async {
    final r = await http.post(
      _u('/api/v1/gateway/start'),
      headers: {'Content-Type': 'application/json'},
      body: jsonEncode({'master_password': masterPassword}),
    );
    _ensure(r);
    return _jsonMap(r.body);
  }

  Future<Map<String, dynamic>> gatewayStop() async {
    final r = await http.post(_u('/api/v1/gateway/stop'));
    _ensure(r);
    return _jsonMap(r.body);
  }

  Future<Map<String, dynamic>> gatewaySnapshot() async {
    final r = await http.get(_u('/api/v1/gateway/snapshot'));
    _ensure(r);
    return _jsonMap(r.body);
  }

  void _ensure(http.Response r) {
    if (r.statusCode >= 200 && r.statusCode < 300) return;
    final body = r.body.isNotEmpty ? r.body : 'HTTP ${r.statusCode}';
    throw ApiException(body);
  }

  Map<String, dynamic> _jsonMap(String body) {
    final obj = jsonDecode(body);
    if (obj is Map<String, dynamic>) return obj;
    throw ApiException('Invalid JSON object response');
  }
}
