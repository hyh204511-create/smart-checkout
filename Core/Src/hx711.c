/* Core/Src/hx711.c */
#include "hx711.h"

// ==================== 硬件引脚配置 ====================
#define HX711_SCK_LOW   HAL_GPIO_WritePin(HX711_SCK_PORT, HX711_SCK_PIN, GPIO_PIN_RESET)
#define HX711_SCK_HIGH  HAL_GPIO_WritePin(HX711_SCK_PORT, HX711_SCK_PIN, GPIO_PIN_SET)
#define HX711_DT_READ   HAL_GPIO_ReadPin(HX711_DT_PORT, HX711_DT_PIN)

// ==================== 算法与滤波参数配置 ====================
#define FILTER_WINDOW_SIZE    10

// 零点稳定逻辑参数 (工业迟滞状态机)
#define BREAK_ZERO_G          50.0f  // 突破死区：大于此值才解除零点锁定
#define RE_ENTER_ZERO_G       10.0f  // 回落死区：拿下重物后，必须降到此值以内才重新锁定为0
#define AUTO_ZERO_TRACKING_G  5.0f   // 零点跟踪阈值
#define TRACKING_TIME_MS      3000   // 稳定触发时间

// 全局标定参数 (可稍后保存到Flash或EEPROM)
static float hx711_coef = 196.2f; 
static int32_t hx711_offset = 0;

// ==================== 底层函数 ====================
static inline void delay_1us_168mhz(void) {
    // 168MHz下，约42个空指令周期为1us
    for(volatile uint32_t i = 0; i < 42; i++) {
        __NOP();
    }
}

static void bubble_sort(int32_t *arr, uint8_t n) {
    for (uint8_t i = 0; i < n - 1; i++) {
        for (uint8_t j = 0; j < n - i - 1; j++) {
            if (arr[j] > arr[j + 1]) {
                int32_t temp = arr[j];
                arr[j] = arr[j + 1];
                arr[j + 1] = temp;
            }
        }
    }
}

// ==================== 核心驱动接口 ====================
int32_t HX711_Read_Raw(void) {
    uint32_t count = 0;
    HX711_SCK_LOW;
    
    uint32_t timeout = HAL_GetTick();
    while(HX711_DT_READ) {
        if((HAL_GetTick() - timeout) > 100) return -1; // 100ms超时保护
    }
    
    __disable_irq(); // 保护时序
    
    for(int i = 0; i < 24; i++) {
        HX711_SCK_HIGH;
        delay_1us_168mhz();
        count = count << 1;
        HX711_SCK_LOW;
        delay_1us_168mhz();
        if(HX711_DT_READ) count++;
    }
    
    HX711_SCK_HIGH;
    delay_1us_168mhz();
    
    if (count & 0x800000) {
        count |= 0xFF000000; // 24位符号扩展
    }
    
    HX711_SCK_LOW;
    // 延迟确保恢复，防止下一次过快拉高导致芯片掉电(PD_SCK > 60us)
    delay_1us_168mhz(); 
    
    __enable_irq(); 
    return (int32_t)count;
}

void HX711_Init_Tare(void) {
    HAL_Delay(100); // 芯片上电稳定时间
    // 抛弃前两次不稳定读数
    HX711_Read_Raw();
    HX711_Read_Raw();
    
    int64_t sum = 0;
    int valid_cnt = 0;
    
    for(int i = 0; i < 10; i++) {
        int32_t val = HX711_Read_Raw();
        if(val != -1) { 
            sum += val;
            valid_cnt++;
        }
        HAL_Delay(5); // 给采样留点余量
    }
    
    if(valid_cnt > 0) {
        hx711_offset = (int32_t)(sum / valid_cnt);
    }
}

// 获取重量：集成了迟滞状态机
float HX711_Get_Weight(void) {
    static int32_t window[FILTER_WINDOW_SIZE] = {0}; 
    static uint8_t count = 0;
    static uint32_t steady_zero_timer = 0;
    static float last_w = 0.0f;
    static uint8_t is_zero_locked = 1;

    int32_t raw = HX711_Read_Raw();
    
    // 不可返回 -9999.0f，直接返回上一次有效值防止滤波器突变
    if(raw == -1) return last_w; 

    // ---------- 1. 中值平均滤波 ----------
    if (count == 0) {
        for(int i=0; i<FILTER_WINDOW_SIZE; i++) window[i] = raw;
        count = FILTER_WINDOW_SIZE;
    }

    for (int i = 0; i < FILTER_WINDOW_SIZE - 1; i++) {
        window[i] = window[i + 1];
    }
    window[FILTER_WINDOW_SIZE - 1] = raw;

    int32_t sort_buf[FILTER_WINDOW_SIZE];
    for (int i = 0; i < FILTER_WINDOW_SIZE; i++) {
        sort_buf[i] = window[i];
    }

    bubble_sort(sort_buf, FILTER_WINDOW_SIZE);

    int64_t sum = 0;
    for(int i = 2; i < FILTER_WINDOW_SIZE - 2; i++) {
        sum += sort_buf[i];
    }
    int32_t avg_raw = (int32_t)(sum / (FILTER_WINDOW_SIZE - 4));

    // 计算当前物理重量
    float w = (float)(avg_raw - hx711_offset) / hx711_coef;

    // ---------- 2. 自动零点跟踪 (吸收环境温漂) ----------
    if (w > -AUTO_ZERO_TRACKING_G && w < AUTO_ZERO_TRACKING_G) {
        if (w - last_w > -1.0f && w - last_w < 1.0f) {
            if (steady_zero_timer == 0) {
                steady_zero_timer = HAL_GetTick(); 
            } else if ((HAL_GetTick() - steady_zero_timer) > TRACKING_TIME_MS) {
                hx711_offset = avg_raw; 
                w = 0.0f; 
                steady_zero_timer = 0; 
            }
        } else {
            steady_zero_timer = 0; 
        }
    } else {
        steady_zero_timer = 0; 
    }
    last_w = w;

    // ---------- 3. 迟滞状态机 (彻底解决跳变) ----------
    if (is_zero_locked) {
        if (w > BREAK_ZERO_G || w < -BREAK_ZERO_G) {
            is_zero_locked = 0; 
        } else {
            w = 0.0f; 
        }
    } else {
        if (w > -RE_ENTER_ZERO_G && w < RE_ENTER_ZERO_G) {
            is_zero_locked = 1; 
            w = 0.0f;
        }
    }

    return w;
}

int32_t HX711_Get_Offset(void) { return hx711_offset; }
float HX711_Get_Coef(void) { return hx711_coef; }

void HX711_Set_Calibration(float coef, int32_t offset) {
    hx711_coef = coef;
    hx711_offset = offset;
}

// 利用已知砝码自动推算比例系数
int8_t HX711_Calibrate_With_Weight(float known_weight_g) {
    if(known_weight_g <= 0) return -1;
    
    int64_t sum = 0;
    int valid_cnt = 0;
    for(int i = 0; i < 10; i++) {
        int32_t val = HX711_Read_Raw();
        if(val != -1) { sum += val; valid_cnt++; }
        HAL_Delay(10);
    }
    if(valid_cnt == 0) return -1;
    
    int32_t current_avg = (int32_t)(sum / valid_cnt);
    hx711_coef = (float)(current_avg - hx711_offset) / known_weight_g;
    return 0; // 成功
}