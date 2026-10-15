package dev.yimeng.nijikori;

import com.google.gson.Gson;
import com.google.gson.GsonBuilder;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;

public final class BridgeConfig {
    private static final Gson GSON = new GsonBuilder().setPrettyPrinting().create();
    public int port = 19683;
    public String token = "";
    public String replyTarget = "game";
    public boolean context = true;

    public BridgeConfig snapshot() {
        BridgeConfig copy = new BridgeConfig();
        copy.port = port; copy.token = token; copy.replyTarget = replyTarget; copy.context = context;
        return copy;
    }

    public static BridgeConfig load(Path path) throws IOException {
        if (!Files.exists(path)) return new BridgeConfig();
        try {
            BridgeConfig config = GSON.fromJson(Files.readString(path), BridgeConfig.class);
            if (config == null || config.port < 1024 || config.port > 65535 || config.token == null
                    || !("game".equals(config.replyTarget) || "pet".equals(config.replyTarget)))
                throw new IllegalArgumentException("invalid configuration");
            return config;
        } catch (RuntimeException e) {
            throw new IOException("联通配置无效，请修复 config/nijikori-bridge.json", e);
        }
    }

    public void save(Path path) throws IOException {
        Files.createDirectories(path.getParent());
        Path temporary = path.resolveSibling(path.getFileName() + ".tmp");
        Files.writeString(temporary, GSON.toJson(this) + "\n", StandardCharsets.UTF_8);
        Files.move(temporary, path, StandardCopyOption.REPLACE_EXISTING);
    }
}
