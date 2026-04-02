/**
 * 百度语音识别 — 语音转文字
 * API已验证可用（2026-03-24）
 * v1.4: 双格式重试(wav->aac/m4a) + base64大小检查 + 用户友好错误信息 + 测试模式
 */

// Baidu API credentials — loaded from local config (not committed to git)
// To set up: create utils/config.js with exports: { BAIDU_API_KEY, BAIDU_SECRET_KEY }
var _config = require('./config.js');
var BAIDU_API_KEY = _config.BAIDU_API_KEY || '';
var BAIDU_SECRET_KEY = _config.BAIDU_SECRET_KEY || '';
var _accessToken = '';
var _tokenExpiry = 0;
var _tokenRequestInFlight = false;
var _tokenCallbackQueue = [];

// Minimum recording duration in milliseconds (3 seconds)
var MIN_RECORDING_DURATION_MS = 3000;
// Minimum audio file size in bytes (~3 seconds of 16kHz mono 16-bit PCM = ~96000 bytes,
// but wav compression and headers vary, so use a conservative threshold)
var MIN_AUDIO_BYTES = 48000;
// Maximum base64 length for safe wx.request JSON body (~500KB)
var MAX_BASE64_LENGTH = 500000;

// User-friendly error messages
var ERROR_MESSAGES = {
  3300: '参数错误，请重试',
  3301: '录音质量不佳，请在安静环境重试',
  3302: '认证过期，请重试',
  3303: '录音太短或太长，请说3-30秒',
  3304: '录音太长，请缩短到30秒以内',
  3305: '服务器识别失败，请重试',
  3307: '服务器内部错误，请稍后重试',
  3308: '录音太长（最长60秒），请缩短',
  3309: '音频数据异常，请重新录音',
  3310: '音频读取失败，请重新录音',
  3311: '采样率不匹配，请重新录音',
  3312: '音频格式不支持，正在自动重试...',
  'network_error': '网络连接失败，请检查WiFi',
  'token_failed': '服务暂时不可用，请稍后重试',
  'base64_too_large': '录音太长，请缩短到10秒以内',
  'recording_too_short': '录音太短，请至少说3秒',
  'audio_too_short': '录音内容太少，请靠近麦克风重试',
};

function getFriendlyError(msgOrCode) {
  if (typeof msgOrCode === 'number') {
    return ERROR_MESSAGES[msgOrCode] || ('错误:' + msgOrCode);
  }
  var str = String(msgOrCode);
  // Check if it starts with a known error code like "3301:..."
  var parts = str.split(':');
  var code = parseInt(parts[0], 10);
  if (!isNaN(code) && ERROR_MESSAGES[code]) {
    return ERROR_MESSAGES[code];
  }
  // Check string keys
  if (str.indexOf('network_error') >= 0) return ERROR_MESSAGES['network_error'];
  if (str.indexOf('token_failed') >= 0) return ERROR_MESSAGES['token_failed'];
  if (str.indexOf('base64_too_large') >= 0) return ERROR_MESSAGES['base64_too_large'];
  if (str.indexOf('recording_too_short') >= 0) return ERROR_MESSAGES['recording_too_short'];
  if (str.indexOf('audio_too_short') >= 0) return ERROR_MESSAGES['audio_too_short'];
  return '识别失败:' + str;
}

function getAccessToken(callback) {
  if (_accessToken && Date.now() < _tokenExpiry) {
    console.log('[Speech] Using cached token, expires in', Math.round((_tokenExpiry - Date.now()) / 1000), 'seconds');
    callback(_accessToken);
    return;
  }

  // Queue callbacks if a token request is already in flight to avoid duplicate requests
  _tokenCallbackQueue.push(callback);
  if (_tokenRequestInFlight) {
    console.log('[Speech] Token request already in flight, queued callback. Queue length:', _tokenCallbackQueue.length);
    return;
  }
  _tokenRequestInFlight = true;

  console.log('[Speech] Requesting new access token...');
  wx.request({
    url: 'https://aip.baidubce.com/oauth/2.0/token?grant_type=client_credentials&client_id=' + BAIDU_API_KEY + '&client_secret=' + BAIDU_SECRET_KEY,
    method: 'POST',
    timeout: 10000,
    success: function(res) {
      console.log('[Speech] Token response status:', res.statusCode);
      if (res.data && res.data.access_token) {
        _accessToken = res.data.access_token;
        // Guard against missing or invalid expires_in
        var expiresIn = (typeof res.data.expires_in === 'number' && res.data.expires_in > 60) ? res.data.expires_in : 3600;
        _tokenExpiry = Date.now() + (expiresIn - 60) * 1000;
        console.log('[Speech] Token OK, expires_in:', expiresIn, 'seconds');
        _flushTokenQueue(_accessToken);
      } else {
        console.error('[Speech] Token error - no access_token in response:', JSON.stringify(res.data));
        console.error('[Speech] Token response statusCode:', res.statusCode);
        _flushTokenQueue('');
      }
    },
    fail: function(err) {
      console.error('[Speech] Token network error:', JSON.stringify(err));
      console.error('[Speech] Check network connectivity and domain whitelist for aip.baidubce.com');
      _flushTokenQueue('');
    }
  });
}

function _flushTokenQueue(token) {
  _tokenRequestInFlight = false;
  var queue = _tokenCallbackQueue.slice();
  _tokenCallbackQueue = [];
  console.log('[Speech] Flushing token queue, callbacks:', queue.length, 'token valid:', !!token);
  queue.forEach(function(cb) { cb(token); });
}

/**
 * Send ASR request with a specific format configuration.
 * @param {string} audioBase64 - Base64-encoded audio data
 * @param {number} rawLen - Raw byte length of the audio file
 * @param {string} token - Baidu access token
 * @param {string} format - Audio format to declare to Baidu ('wav', 'm4a', 'pcm', etc.)
 * @param {function} callback - Called with {success, text, msg, errNo, raw}
 */
function _sendAsrRequest(audioBase64, rawLen, token, format, callback) {
  var payload = {
    format: format,
    rate: 16000,
    channel: 1,
    cuid: 'chuanjia_legacy',
    token: token,
    speech: audioBase64,
    len: rawLen,
    dev_pid: 1537
  };

  console.log('[Speech] Sending ASR request: format=' + format + ', rate=16000, channel=1, len=' + rawLen + ', dev_pid=1537');

  wx.request({
    url: 'https://vop.baidu.com/server_api',
    method: 'POST',
    header: { 'Content-Type': 'application/json' },
    timeout: 30000,
    data: JSON.stringify(payload),
    success: function(apiRes) {
      console.log('[Speech] ASR HTTP status:', apiRes.statusCode, 'format:', format);
      console.log('[Speech] ASR response:', JSON.stringify(apiRes.data));

      if (apiRes.statusCode !== 200) {
        console.error('[Speech] ASR HTTP error, status:', apiRes.statusCode);
        callback({ success: false, text: '', msg: 'http_' + apiRes.statusCode, errNo: -1, raw: apiRes.data });
        return;
      }

      if (apiRes.data && apiRes.data.err_no === 0 && apiRes.data.result) {
        var text = apiRes.data.result.join('');
        text = text.replace(/[，。、！？,\.!?\s]+$/g, '').trim();
        console.log('[Speech] ASR success, text length:', text.length, 'text:', text);
        if (text) {
          callback({ success: true, text: text, msg: 'ok', errNo: 0, raw: apiRes.data });
        } else {
          console.warn('[Speech] ASR returned empty text after cleanup');
          callback({ success: false, text: '', msg: 'empty_result', errNo: 0, raw: apiRes.data });
        }
      } else {
        var errNo = apiRes.data ? apiRes.data.err_no : -1;
        var errMsg = apiRes.data ? apiRes.data.err_msg : 'unknown';
        var sn = apiRes.data ? apiRes.data.sn : '';
        console.error('[Speech] ASR error code:', errNo, 'msg:', errMsg, 'sn:', sn, 'format:', format);

        // Diagnostic info based on error code
        if (errNo === 3300) console.error('[Speech] Error 3300: Input parameter error.');
        if (errNo === 3301) console.error('[Speech] Error 3301: Audio quality problem.');
        if (errNo === 3302) console.error('[Speech] Error 3302: Authentication failed.');
        if (errNo === 3303) console.error('[Speech] Error 3303: Voice too short or too long.');
        if (errNo === 3304) console.error('[Speech] Error 3304: Audio data exceeds limit.');
        if (errNo === 3305) console.error('[Speech] Error 3305: DNN error.');
        if (errNo === 3307) console.error('[Speech] Error 3307: Server internal error.');
        if (errNo === 3308) console.error('[Speech] Error 3308: Audio too long (max 60s).');
        if (errNo === 3309) console.error('[Speech] Error 3309: Audio length mismatch!');
        if (errNo === 3310) console.error('[Speech] Error 3310: Audio read error.');
        if (errNo === 3311) console.error('[Speech] Error 3311: Sampling rate error.');
        if (errNo === 3312) console.error('[Speech] Error 3312: Audio format error.');

        callback({ success: false, text: '', msg: errNo + ':' + errMsg, errNo: errNo, raw: apiRes.data });
      }
    },
    fail: function(err) {
      console.error('[Speech] ASR network fail:', JSON.stringify(err), 'format:', format);
      callback({ success: false, text: '', msg: 'network_error', errNo: -1, raw: err });
    }
  });
}

/**
 * Recognize speech from an audio file.
 * v1.4: Tries wav first, then automatically retries with m4a format on 3301/3312 errors.
 * @param {string} filePath - Path to the audio file
 * @param {function} callback - Called with {success, text, msg, friendlyMsg}
 * @param {number} [_retryCount] - Internal retry counter
 * @param {number} [recordingDurationMs] - Optional: actual recording duration in ms
 * @param {object} [options] - Optional: {testMode: bool} for detailed diagnostic output
 */
function recognizeSpeech(filePath, callback, _retryCount, recordingDurationMs, options) {
  if (typeof _retryCount === 'undefined') _retryCount = 0;
  var MAX_RETRIES = 1;
  var testMode = options && options.testMode;

  if (!filePath) {
    console.error('[Speech] recognizeSpeech called with empty filePath');
    callback({ success: false, text: '', msg: 'no_file_path', friendlyMsg: '未找到录音文件' });
    return;
  }

  console.log('[Speech] recognizeSpeech called, filePath:', filePath, 'retry:', _retryCount, 'testMode:', !!testMode);

  // Check minimum recording duration if provided
  if (typeof recordingDurationMs === 'number' && recordingDurationMs < MIN_RECORDING_DURATION_MS) {
    console.warn('[Speech] Recording too short:', recordingDurationMs, 'ms');
    var shortMsg = 'recording_too_short_' + recordingDurationMs + 'ms';
    callback({ success: false, text: '', msg: shortMsg, friendlyMsg: getFriendlyError('recording_too_short') });
    return;
  }

  getAccessToken(function(token) {
    if (!token) {
      console.error('[Speech] Cannot proceed: no valid access token');
      callback({ success: false, text: '', msg: 'token_failed', friendlyMsg: getFriendlyError('token_failed') });
      return;
    }

    var fs = wx.getFileSystemManager();

    fs.readFile({
      filePath: filePath,
      success: function(rawRes) {
        var rawLen = rawRes.data.byteLength;
        console.log('[Speech] Audio raw byte length:', rawLen, 'bytes');

        // Guard against empty or too-short audio files (skip check in test mode)
        if (!testMode && rawLen < MIN_AUDIO_BYTES) {
          console.warn('[Speech] Audio file too small:', rawLen, 'bytes');
          var tinyMsg = 'audio_too_short_' + rawLen + 'bytes';
          callback({ success: false, text: '', msg: tinyMsg, friendlyMsg: getFriendlyError('audio_too_short') });
          return;
        }

        fs.readFile({
          filePath: filePath,
          encoding: 'base64',
          success: function(b64Res) {
            var audioBase64 = b64Res.data;
            var base64Len = audioBase64.length;
            console.log('[Speech] Base64 length:', base64Len, 'chars');

            // Base64 size check - warn if too large for reliable wx.request
            if (base64Len > MAX_BASE64_LENGTH) {
              console.warn('[Speech] Base64 too large:', base64Len, '> max', MAX_BASE64_LENGTH);
              callback({
                success: false, text: '', msg: 'base64_too_large',
                friendlyMsg: getFriendlyError('base64_too_large'),
                diagnostics: { rawLen: rawLen, base64Len: base64Len }
              });
              return;
            }

            // === Strategy: Try wav first, then m4a on format-related errors ===
            _sendAsrRequest(audioBase64, rawLen, token, 'wav', function(wavResult) {
              // Add friendlyMsg
              wavResult.friendlyMsg = getFriendlyError(wavResult.errNo || wavResult.msg);

              if (wavResult.success) {
                if (testMode) {
                  wavResult.diagnostics = { rawLen: rawLen, base64Len: base64Len, formatUsed: 'wav', errNo: 0 };
                }
                callback(wavResult);
                return;
              }

              // On 3301 (quality) or 3312 (format error), retry with m4a format
              // These errors often mean iPhone's wav variant isn't recognized by Baidu
              var shouldRetryFormat = (wavResult.errNo === 3301 || wavResult.errNo === 3312);

              if (shouldRetryFormat) {
                console.log('[Speech] wav failed with', wavResult.errNo, '- retrying with m4a format...');
                _sendAsrRequest(audioBase64, rawLen, token, 'm4a', function(m4aResult) {
                  m4aResult.friendlyMsg = getFriendlyError(m4aResult.errNo || m4aResult.msg);

                  if (testMode) {
                    m4aResult.diagnostics = {
                      rawLen: rawLen, base64Len: base64Len,
                      wavErrNo: wavResult.errNo, m4aErrNo: m4aResult.errNo,
                      formatUsed: m4aResult.success ? 'm4a' : 'both_failed'
                    };
                  }

                  if (m4aResult.success) {
                    console.log('[Speech] m4a format succeeded after wav failed!');
                    callback(m4aResult);
                  } else {
                    console.error('[Speech] Both wav and m4a failed. wav:', wavResult.errNo, 'm4a:', m4aResult.errNo);
                    // Return the m4a result but with combined info
                    m4aResult.msg = 'dual_fail:wav=' + wavResult.errNo + ',m4a=' + m4aResult.errNo;
                    m4aResult.friendlyMsg = '两种格式均失败，请在安静环境靠近麦克风重试';
                    callback(m4aResult);
                  }
                });
                return;
              }

              // On 3302 (auth expired), refresh token and retry
              if (wavResult.errNo === 3302 && _retryCount < MAX_RETRIES) {
                console.log('[Speech] Token expired, refreshing and retrying...');
                _accessToken = '';
                _tokenExpiry = 0;
                recognizeSpeech(filePath, callback, _retryCount + 1, recordingDurationMs, options);
                return;
              }

              // On network error, retry once
              if (wavResult.msg === 'network_error' && _retryCount < MAX_RETRIES) {
                console.log('[Speech] Network error, retrying...');
                recognizeSpeech(filePath, callback, _retryCount + 1, recordingDurationMs, options);
                return;
              }

              // All other errors - return as-is with friendly message
              if (testMode) {
                wavResult.diagnostics = { rawLen: rawLen, base64Len: base64Len, formatUsed: 'wav', errNo: wavResult.errNo };
              }
              callback(wavResult);
            });
          },
          fail: function(err) {
            console.error('[Speech] Failed to read audio as base64:', JSON.stringify(err));
            callback({ success: false, text: '', msg: 'b64_read_error', friendlyMsg: '音频文件读取失败' });
          }
        });
      },
      fail: function(err) {
        console.error('[Speech] Failed to read raw audio file:', JSON.stringify(err));
        callback({ success: false, text: '', msg: 'raw_read_error', friendlyMsg: '音频文件读取失败' });
      }
    });
  });
}

module.exports = {
  recognizeSpeech: recognizeSpeech,
  getFriendlyError: getFriendlyError,
  MIN_RECORDING_DURATION_MS: MIN_RECORDING_DURATION_MS,
  ERROR_MESSAGES: ERROR_MESSAGES,
};
