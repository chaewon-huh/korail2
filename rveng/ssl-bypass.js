// Broader SSL pinning bypass for common Android stacks (Conscrypt/OkHttp/WebView/SSLSocketFactory).
// If native pinning exists, further hooks may be needed.
Java.perform(function () {
  function tryHook(desc, fn) {
    try {
      fn();
      console.log("[+] " + desc + " bypassed");
    } catch (e) {
      console.log("[-] " + desc + " hook failed: " + e);
    }
  }

  // Conscrypt (AOSP)
  tryHook("TrustManagerImpl.verifyChain", function () {
    var TrustManagerImpl = Java.use("com.android.org.conscrypt.TrustManagerImpl");
    TrustManagerImpl.verifyChain.implementation = function (chain, authType, session, params, authType2) {
      return chain;
    };
  });

  // Conscrypt variants: OpenSSLSocketImpl verifySessionChain
  tryHook("OpenSSLSocketImpl verifySessionChain", function () {
    [
      "com.android.org.conscrypt.OpenSSLSocketImpl",
      "org.conscrypt.OpenSSLSocketImpl",
      "com.google.android.gms.org.conscrypt.OpenSSLSocketImpl",
    ].forEach(function (cls) {
      try {
        var Impl = Java.use(cls);
        Impl.verifySessionChain.implementation = function (untrustedChain, trustManager, host, client) {
          return;
        };
        console.log("[+] " + cls + ".verifySessionChain bypassed");
      } catch (e) {
        console.log("[-] " + cls + " hook failed: " + e);
      }
    });
  });

  // HttpsURLConnection - setDefaultHostnameVerifier / setHostnameVerifier
  tryHook("HttpsURLConnection hostname verifier", function () {
    var HV = Java.registerClass({
      name: "org.leviathan.HV",
      implements: [Java.use("javax.net.ssl.HostnameVerifier")],
      methods: {
        verify: function (hostname, session) {
          return true;
        },
      },
    });
    var Huc = Java.use("javax.net.ssl.HttpsURLConnection");
    Huc.setDefaultHostnameVerifier.implementation = function (v) {
      return this.setDefaultHostnameVerifier(HV.$new());
    };
    Huc.setHostnameVerifier.implementation = function (v) {
      return this.setHostnameVerifier(HV.$new());
    };
  });

  // Generic TrustManager[] injection into SSLContext.init
  tryHook("SSLContext.init TrustManagers", function () {
    var X509TM = Java.use("javax.net.ssl.X509TrustManager");
    var SSLContext = Java.use("javax.net.ssl.SSLContext");
    var TM = Java.registerClass({
      name: "org.leviathan.TM",
      implements: [X509TM],
      methods: {
        checkClientTrusted: function (chain, authType) {},
        checkServerTrusted: function (chain, authType) {},
        getAcceptedIssuers: function () {
          return [];
        },
      },
    });
    SSLContext.init.overload(
      "[Ljavax.net.ssl.KeyManager;",
      "[Ljavax.net.ssl.TrustManager;",
      "java.security.SecureRandom"
    ).implementation = function (km, tm, sr) {
      var tms = [TM.$new()];
      return this.init(km, tms, sr);
    };
  });

  // OkHttp3
  tryHook("okhttp3.CertificatePinner", function () {
    var CertificatePinner = Java.use("okhttp3.CertificatePinner");
    CertificatePinner.check.overload("java.lang.String", "java.util.List").implementation = function (a, b) {
      return;
    };
    CertificatePinner.check.overload("java.lang.String", "java.util.List", "java.util.List").implementation = function (a, b, c) {
      return;
    };
  });

  // OkHttp <3
  tryHook("com.squareup.okhttp.CertificatePinner", function () {
    var CertificatePinner = Java.use("com.squareup.okhttp.CertificatePinner");
    CertificatePinner.check.overload("java.lang.String", "java.util.List").implementation = function (a, b) {
      return;
    };
    CertificatePinner.check.overload("java.lang.String", "java.util.List", "java.util.List").implementation = function (a, b, c) {
      return;
    };
  });

  // WebView SSL error handler
  tryHook("WebViewClient.onReceivedSslError", function () {
    var WebViewClient = Java.use("android.webkit.WebViewClient");
    WebViewClient.onReceivedSslError.implementation = function (view, handler, error) {
      handler.proceed();
    };
  });

  // Debug: list loaded classes containing 'okhttp' or 'ssl'
  try {
    var matches = [];
    Java.enumerateLoadedClassesSync().forEach(function (c) {
      if (c.indexOf("okhttp") >= 0 || c.indexOf("ssl") >= 0 || c.indexOf("pin") >= 0) {
        matches.push(c);
      }
    });
    console.log("[*] Loaded classes (subset): " + matches.slice(0, 50).join(", "));
  } catch (e) {
    console.log("[-] enumerateLoadedClasses failed: " + e);
  }

  // Extra: GMS/org.conscrypt TrustManagerImpl variants
  ["com.google.android.gms.org.conscrypt.TrustManagerImpl", "org.conscrypt.TrustManagerImpl"].forEach(function (cls) {
    tryHook(cls + ".verifyChain", function () {
      var T = Java.use(cls);
      T.verifyChain.implementation = function (chain, authType, session, params, authType2) {
        return chain;
      };
    });
  });

  // Extra: brute-force common pinning/verify methods in loaded classes
  try {
    Java.enumerateLoadedClassesSync().forEach(function (c) {
      if (c.indexOf("pin") >= 0 || c.indexOf("Pin") >= 0 || c.indexOf("Trust") >= 0 || c.indexOf("SSL") >= 0) {
        try {
          var k = Java.use(c);
          ["check", "verify", "a", "b", "c", "d"].forEach(function (m) {
            if (k[m]) {
              k[m].overloads.forEach(function (ov) {
                ov.implementation = function () {
                  return true;
                };
              });
              console.log("[+] Patched " + c + "." + m);
            }
          });
        } catch (e) {
          // ignore noisy failures
        }
      }
    });
  } catch (e) {
    console.log("[-] brute-force hook loop failed: " + e);
  }
});
