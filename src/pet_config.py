"""Validate persistent configuration before replacing a working snapshot."""
import json
import math
import os


class ConfigError(ValueError):
    pass


def validate_config(data):
    if not isinstance(data, dict):
        raise ConfigError('配置必须是 JSON 对象')
    strings = ('base_url', 'api_key', 'model', 'system_prompt',
               'current_emotion', 'harness_dsh_path', 'harness_status_url',
               'harness_sessions_dir', 'harness_monitor_source')
    for key in strings:
        if key in data and not isinstance(data[key], str):
            raise ConfigError(f'{key} 必须是文本')
    for key, value in data.items():
        if (key.startswith('enable_') or key in ('always_on_top', 'confirm_before_command',
                                                'delete_easter_egg_move_to_file')):
            if not isinstance(value, bool):
                raise ConfigError(f'{key} 必须是 true 或 false')
    for key in ('pet_size', 'pet_fps', 'x', 'y', 'max_tool_rounds', 'low_balance_threshold',
                'balance_check_interval_mins', 'sleep_timeout_mins', 'wander_interval_secs',
                'harness_poll_interval_secs'):
        if key not in data:
            continue
        value = data[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ConfigError(f'{key} 必须是有限数值')
        if key not in ('x', 'y') and value < 0:
            raise ConfigError(f'{key} 不能为负数')
        if key in ('pet_size', 'pet_fps') and value == 0:
            raise ConfigError(f'{key} 必须大于 0')
    if 'web_search_timeout_secs' in data:
        value = data['web_search_timeout_secs']
        if (isinstance(value, bool) or not isinstance(value, (int, float)) or
                not math.isfinite(value) or not 3 <= value <= 30):
            raise ConfigError('web_search_timeout_secs 必须是 3 ~ 30 秒的有限数值')
    if 'web_search_max_results' in data:
        value = data['web_search_max_results']
        if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 10:
            raise ConfigError('web_search_max_results 必须是 1 ~ 10 的整数')
    if 'chat_size' in data:
        size = data['chat_size']
        if not isinstance(size, dict) or set(size) != {'w', 'h'} or any(
                isinstance(v, bool) or not isinstance(v, (int, float)) or
                not math.isfinite(v) or v <= 0 for v in size.values()):
            raise ConfigError('chat_size 的 w 和 h 必须为正数')
    if 'disabled_tools' in data and not (isinstance(data['disabled_tools'], str) or
            isinstance(data['disabled_tools'], list) and all(isinstance(v, str) for v in data['disabled_tools'])):
        raise ConfigError('disabled_tools 必须是工具名称列表')
    if 'reminders' in data:
        reminders = data['reminders']
        if not isinstance(reminders, list) or not all(isinstance(r, dict) for r in reminders):
            raise ConfigError('reminders 必须是任务对象列表')
        for task in reminders:
            for key in ('due', 'runs', 'repeat_count', 'interval_value', 'day_of_month'):
                if key in task:
                    value = task[key]
                    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                        raise ConfigError(f'定时任务的 {key} 必须是有限数值')
            for key in ('id', 'message', 'task_type', 'task_target', 'repeat', 'at_time', 'cron'):
                if key in task and not isinstance(task[key], str):
                    raise ConfigError(f'定时任务的 {key} 必须是文本')
    return data


def read_config(path):
    if not os.path.exists(path):
        return {}
    try:
        with open(path, 'r', encoding='utf-8-sig') as f:
            data = json.load(f)
    except (OSError, ValueError, UnicodeError) as exc:
        # Report syntax/location, never include configuration values or keys.
        raise ConfigError(f'配置文件读取失败：{type(exc).__name__}') from exc
    data = validate_config(data)
    # Retired search-model settings must never reach the search tool or get saved again.
    data.pop("search_model", None)
    return data
