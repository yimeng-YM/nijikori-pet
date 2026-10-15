package dev.yimeng.nijikori;

import com.google.gson.JsonObject;
import com.mojang.brigadier.arguments.IntegerArgumentType;
import com.mojang.brigadier.arguments.StringArgumentType;
import java.io.IOException;
import java.nio.file.Path;
import net.fabricmc.api.ClientModInitializer;
import net.fabricmc.fabric.api.client.command.v2.ClientCommandRegistrationCallback;
import net.fabricmc.fabric.api.client.event.lifecycle.v1.ClientLifecycleEvents;
import net.fabricmc.fabric.api.client.networking.v1.ClientPlayConnectionEvents;
import net.fabricmc.loader.api.FabricLoader;
import net.minecraft.client.MinecraftClient;
import net.minecraft.registry.Registries;
import net.minecraft.text.Text;
import net.minecraft.util.hit.BlockHitResult;
import net.minecraft.util.hit.EntityHitResult;
import static net.fabricmc.fabric.api.client.command.v2.ClientCommandManager.*;

public final class NijikoriClient implements ClientModInitializer {
    private static final Path CONFIG = FabricLoader.getInstance().getConfigDir().resolve("nijikori-bridge.json");
    private BridgeConfig config;
    private BridgeTransport bridge;
    private String configError;

    public void onInitializeClient() {
        try { config = BridgeConfig.load(CONFIG); }
        catch (IOException e) { config = new BridgeConfig(); configError = e.getMessage(); }
        bridge = new BridgeTransport(config, event -> {
            MinecraftClient client = MinecraftClient.getInstance();
            var connection = client.getNetworkHandler();
            client.execute(() -> {
                if (client.player == null || client.getNetworkHandler() != connection) return;
                String kind = event.get("kind").getAsString();
                if ("delivered".equals(kind)) local("[虹语织] 桌宠已回复。");
                else local(("error".equals(kind) ? "[虹语织提示] " : "[虹语织] ") + event.get("text").getAsString());
            });
        });
        ClientPlayConnectionEvents.JOIN.register((handler, sender, client) -> bridge.setOnline(true));
        ClientPlayConnectionEvents.DISCONNECT.register((handler, client) -> bridge.setOnline(false));
        ClientLifecycleEvents.CLIENT_STOPPING.register(client -> bridge.close());
        ClientCommandRegistrationCallback.EVENT.register((dispatcher, registry) -> {
            for (String alias : new String[]{"c", "chat"}) dispatcher.register(literal(alias)
                    .executes(ctx -> help())
                    .then(argument("message", StringArgumentType.greedyString()).executes(ctx -> send(StringArgumentType.getString(ctx, "message")))));
            dispatcher.register(literal("nijikori").executes(ctx -> help())
                    .then(literal("pair").then(argument("port", IntegerArgumentType.integer(1024, 65535))
                            .then(argument("token", StringArgumentType.word()).executes(ctx -> {
                                String token = StringArgumentType.getString(ctx, "token");
                                if (!token.matches("[A-Za-z0-9_-]{20,200}")) { local("配对令牌无效，请重新复制。"); return 0; }
                                config.port = IntegerArgumentType.getInteger(ctx, "port"); config.token = token;
                                return save("已保存配对。可以使用 /c 内容 开始对话。");
                            }))))
                    .then(literal("reply").then(literal("game").executes(ctx -> reply("game")))
                            .then(literal("pet").executes(ctx -> reply("pet"))))
                    .then(literal("context").then(literal("on").executes(ctx -> scene(true)))
                            .then(literal("off").executes(ctx -> scene(false))))
                    .then(literal("status").executes(ctx -> {
                        local("本机端口 " + config.port + "；" + (config.token.isBlank() ? "尚未配对" : "已保存配对")
                                + "；回复位置 " + config.replyTarget + "；场景信息 " + (config.context ? "开" : "关"));
                        return 1;
                    })));
        });
    }

    private int reply(String target) { config.replyTarget = target; return save("回复位置已设为" + (target.equals("game") ? "游戏内" : "桌宠") + "。"); }
    private int scene(boolean enabled) { config.context = enabled; return save("场景信息已" + (enabled ? "开启" : "关闭") + "。"); }
    private int save(String tip) {
        try { config.save(CONFIG); bridge.configure(config); configError = null; local(tip); return 1; }
        catch (IOException e) { local("配置保存失败：" + e.getMessage()); return 0; }
    }
    private int help() {
        local("/c 内容 或 /chat 内容：向桌宠发送；/nijikori reply game|pet：回复位置；/nijikori context on|off：场景信息；在桌宠插件页面复制配对命令。");
        if (configError != null) local(configError);
        return 1;
    }
    private int send(String message) {
        if (configError != null) { local(configError); return 0; }
        if (config.token.isBlank()) { local("请先到桌宠「Minecraft 联通」页面复制配对命令，在这里粘贴执行。"); return 0; }
        if (message.isBlank() || message.length() > 8000) { local("消息长度必须为 1~8000 字符。"); return 0; }
        if (bridge.send(message, config.context ? context() : new JsonObject())) {
            local("[你 → 虹语织] " + message); return 1;
        }
        return 0;
    }
    private JsonObject context() {
        JsonObject result = new JsonObject();
        MinecraftClient client = MinecraftClient.getInstance();
        if (client.player == null || client.world == null) return result;
        var player = client.player;
        result.addProperty("version", "Java 1.21.11");
        result.addProperty("mode", client.isInSingleplayer() ? "单人游戏" : "多人游戏（私人客户端对话）");
        result.addProperty("dimension", client.world.getRegistryKey().getValue().toString());
        result.addProperty("position", player.getBlockPos().toShortString());
        result.addProperty("health", player.getHealth()); result.addProperty("food", player.getHungerManager().getFoodLevel());
        result.addProperty("held_item", Registries.ITEM.getId(player.getMainHandStack().getItem()).toString());
        result.addProperty("weather", client.world.isThundering() ? "雷雨" : client.world.isRaining() ? "下雨" : "晴朗");
        result.addProperty("time", client.world.getTimeOfDay() % 24000);
        result.addProperty("biome", client.world.getBiome(player.getBlockPos()).getKey().map(k -> k.getValue().toString()).orElse("unknown"));
        if (client.crosshairTarget instanceof BlockHitResult hit)
            result.addProperty("looking_at", Registries.BLOCK.getId(client.world.getBlockState(hit.getBlockPos()).getBlock()).toString());
        else if (client.crosshairTarget instanceof EntityHitResult hit)
            result.addProperty("looking_at", Registries.ENTITY_TYPE.getId(hit.getEntity().getType()).toString());
        return result;
    }
    private static void local(String message) {
        MinecraftClient client = MinecraftClient.getInstance();
        if (client.player != null) client.inGameHud.getChatHud().addMessage(Text.literal(message));
    }
}
