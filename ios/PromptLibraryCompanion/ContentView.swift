import SwiftUI
import WebKit

struct ContentView: View {
    @AppStorage("serverURL") private var serverURL = ""
    @State private var draft = ""
    @State private var connected = false
    @State private var failed = false

    var body: some View {
        if connected, let url = URL(string: serverURL) {
            PromptWebView(url: url) {
                failed = true
                connected = false
            }
            .ignoresSafeArea(edges: .bottom)
        } else {
            NavigationStack {
                Form {
                    Section(header: Text("Mac address"),
                            footer: Text("Use your Mac's address: http://your-mac-address:5757/ with Tailscale on (works anywhere), or its Wi-Fi address at home. Prompt Library Pro must be open on the Mac and ~/Documents/PromptLibrary/lan_mode must exist.")) {
                        TextField("http://your-mac-address:5757/", text: $draft)
                            .textInputAutocapitalization(.never)
                            .autocorrectionDisabled()
                            .keyboardType(.URL)
                    }
                    if failed {
                        Text("Couldn't open your library. Check that Prompt Library Pro is open on your Mac, Tailscale is on, and the address is right.")
                            .foregroundColor(.red)
                    }
                    Button("Connect") {
                        var v = draft.trimmingCharacters(in: .whitespaces)
                        if !v.hasPrefix("http") { v = "http://" + v }
                        serverURL = v
                        failed = false
                        connected = true
                    }
                    .disabled(draft.isEmpty)
                }
                .navigationTitle("Prompt Library")
                .onAppear {
                    draft = serverURL
                    if !serverURL.isEmpty && !failed { connected = true }
                }
            }
        }
    }
}

struct PromptWebView: UIViewRepresentable {
    let url: URL
    let onFail: () -> Void

    func makeCoordinator() -> Coordinator { Coordinator(onFail) }

    func makeUIView(context: Context) -> WKWebView {
        let config = WKWebViewConfiguration()
        // Let the page draw under the notch/home bar and respect safe areas.
        let js = """
        var m = document.querySelector('meta[name=viewport]');
        if (m) m.setAttribute('content', 'width=device-width, initial-scale=1, viewport-fit=cover');
        """
        config.userContentController.addUserScript(
            WKUserScript(source: js, injectionTime: .atDocumentEnd, forMainFrameOnly: true))
        let web = WKWebView(frame: .zero, configuration: config)
        web.navigationDelegate = context.coordinator
        web.allowsBackForwardNavigationGestures = true
        web.load(URLRequest(url: url))
        return web
    }

    func updateUIView(_ web: WKWebView, context: Context) {}

    final class Coordinator: NSObject, WKNavigationDelegate {
        let onFail: () -> Void
        init(_ onFail: @escaping () -> Void) { self.onFail = onFail }
        func webView(_ w: WKWebView, didFailProvisionalNavigation n: WKNavigation!, withError e: Error) { onFail() }

        // The Mac answers 403 when phone access is off or the link's token has changed.
        func webView(_ w: WKWebView, decidePolicyFor response: WKNavigationResponse,
                     decisionHandler: @escaping (WKNavigationResponsePolicy) -> Void) {
            if let http = response.response as? HTTPURLResponse, http.statusCode == 403 {
                decisionHandler(.cancel)
                onFail()
                return
            }
            decisionHandler(.allow)
        }
    }
}
