package dev.yimeng.nijikori;

import com.google.gson.*;
import java.net.URI;
import java.net.Proxy;
import java.net.ProxySelector;
import java.net.SocketAddress;
import java.io.IOException;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.List;
import java.util.UUID;
import java.util.concurrent.ScheduledThreadPoolExecutor;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.function.Consumer;

/** The only network peer is the paired loopback pet; never a Minecraft server. */
public final class BridgeTransport implements AutoCloseable {
    private final ScheduledThreadPoolExecutor worker = new ScheduledThreadPoolExecutor(1, runnable -> {
        Thread thread = new Thread(runnable, "Nijikori-local-bridge"); thread.setDaemon(true); return thread;
    });
    private final HttpClient http = HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(2))
            .proxy(new ProxySelector() {
                public List<Proxy> select(URI uri) { return List.of(Proxy.NO_PROXY); }
                public void connectFailed(URI uri, SocketAddress address, IOException error) { }
            }).followRedirects(HttpClient.Redirect.NEVER).build();
    private volatile String clientId = UUID.randomUUID().toString();
    private final AtomicInteger queued = new AtomicInteger();
    private final Consumer<JsonObject> eventConsumer;
    private volatile BridgeConfig config;
    private volatile boolean online;
    private volatile long generation;
    private long cursor;
    private String instance = "";
    private String previousError = "";

    public BridgeTransport(BridgeConfig config, Consumer<JsonObject> eventConsumer) {
        this.config = config.snapshot(); this.eventConsumer = eventConsumer;
        worker.setRemoveOnCancelPolicy(true);
        worker.scheduleWithFixedDelay(this::poll, 0, 1, TimeUnit.SECONDS);
    }

    public void setOnline(boolean online) {
        if (this.online != online) {
            generation++;
            if (online) clientId = UUID.randomUUID().toString();
            this.online = online;
            worker.execute(() -> { cursor = 0; instance = ""; });
        }
    }

    public void configure(BridgeConfig config) {
        BridgeConfig previous = this.config;
        this.config = config.snapshot();
        if (previous.port != config.port || !previous.token.equals(config.token)) {
            generation++;
            clientId = UUID.randomUUID().toString();
            worker.execute(() -> { cursor = 0; instance = ""; previousError = ""; });
        }
    }

    public boolean send(String message, JsonObject context) {
        if (queued.incrementAndGet() > 8) { queued.decrementAndGet(); error("待发送消息过多，请稍后再试。"); return false; }
        BridgeConfig current = config;
        long epoch = generation;
        JsonObject body = new JsonObject();
        body.addProperty("id", UUID.randomUUID().toString()); body.addProperty("client", clientId);
        body.addProperty("message", message); body.addProperty("reply_target", current.replyTarget);
        body.add("context", context);
        worker.execute(() -> {
            try {
                if (!online || epoch != generation) return;
                request(current, "/v1/messages", body.toString());
                previousError = "";
            } catch (Exception e) {
                if (online && epoch == generation) error(friendly(e));
            } finally { queued.decrementAndGet(); }
        });
        return true;
    }

    private JsonObject request(BridgeConfig current, String path, String body) throws Exception {
        HttpRequest.Builder request = HttpRequest.newBuilder(URI.create("http://127.0.0.1:" + current.port + path))
                .timeout(Duration.ofSeconds(5)).header("Authorization", "Bearer " + current.token);
        if (body != null) request.header("Content-Type", "application/json").POST(HttpRequest.BodyPublishers.ofString(body));
        else request.GET();
        HttpResponse<String> response = http.send(request.build(), HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
        if (response.body().length() > 1048576) throw new IOException("桌宠响应过大");
        if (response.statusCode() == 403) throw new IOException("配对失效，请从桌宠插件页面重新复制配对命令。");
        if (response.statusCode() / 100 != 2) {
            String tip = "桌宠暂时无法接收消息（HTTP " + response.statusCode() + "）";
            try { tip += "：" + JsonParser.parseString(response.body()).getAsJsonObject().get("error").getAsString(); }
            catch (RuntimeException ignored) { }
            throw new IOException(tip);
        }
        return JsonParser.parseString(response.body()).getAsJsonObject();
    }

    private void poll() {
        BridgeConfig current = config;
        long epoch = generation;
        if (!online || current.token.isBlank()) return;
        try {
            JsonObject result = request(current, "/v1/events?client=" + clientId + "&after=" + cursor, null);
            if (!online || epoch != generation) return;
            String next = result.get("instance").getAsString();
            if (!instance.isEmpty() && !instance.equals(next)) {
                cursor = 0; instance = next;
                return; // Fetch the new process from zero on the next poll.
            }
            instance = next;
            if (result.has("gap") && result.get("gap").getAsBoolean()) error("离线期间部分消息已过期，请重新发送问题。");
            for (JsonElement item : result.getAsJsonArray("events")) {
                JsonObject event = item.getAsJsonObject();
                long sequence = event.get("seq").getAsLong();
                if (sequence <= cursor) continue;
                eventConsumer.accept(event);
                cursor = sequence;
            }
            cursor = Math.max(cursor, result.get("seq").getAsLong());
            previousError = "";
        } catch (Exception e) {
            String message = friendly(e);
            if (online && epoch == generation && !message.equals(previousError)) {
                error(message); previousError = message;
            }
        }
    }

    private String friendly(Exception error) {
        if (error instanceof java.net.ConnectException) return "桌宠消息桥未连接，请检查桌宠是否启动、插件是否启用及端口是否一致。";
        if (error instanceof java.net.http.HttpTimeoutException) return "桌宠消息桥暂时没有响应，稍后会自动重连。";
        return error instanceof IOException && error.getMessage() != null ? error.getMessage() : "桌宠消息桥通信失败，稍后会自动重连。";
    }

    private void error(String text) {
        JsonObject event = new JsonObject(); event.addProperty("kind", "error"); event.addProperty("text", text);
        eventConsumer.accept(event);
    }

    public void close() { online = false; generation++; worker.shutdownNow(); }
}
