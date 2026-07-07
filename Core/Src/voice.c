/* Core/Src/voice.c */
#include "voice.h"
#include <string.h>
#include <stdarg.h>
#include "stm32f4xx_hal.h"

// 引用 main.c 中的 huart3 (PB10/PB11)
extern UART_HandleTypeDef huart3; 

// SYN6288 核心协议发送函数
static void SYN6288_Send(uint8_t *data, uint16_t len) {
    uint8_t frame[210];
    uint8_t xor_sum = 0;
    
    uint16_t data_area_len = len + 3; 
    
    frame[0] = 0xFD;                     // 帧头
    frame[1] = (data_area_len >> 8);     // 长度高位
    frame[2] = (data_area_len & 0xFF);   // 长度低位
    frame[3] = 0x01;                     // 命令字: 播放
    frame[4] = 0x01;                     // 参数: GBK
    
    memcpy(&frame[5], data, len);
    
    for(int i = 0; i < (5 + len); i++) {
        xor_sum ^= frame[i];
    }
    frame[5 + len] = xor_sum;
    
    // 使用 huart3 发送语音帧
    HAL_UART_Transmit(&huart3, frame, 5 + len + 1, 100);
}

void Voice_Speak(const char* fmt, ...) {
    static uint8_t Voice_Buffer[200];
    va_list args;
    
    va_start(args, fmt);
    int len = vsnprintf((char*)Voice_Buffer, sizeof(Voice_Buffer), fmt, args);
    va_end(args);
    
    if(len > 0 && len <= 200) {
        SYN6288_Send(Voice_Buffer, len);
        HAL_Delay(20); // 给语音芯片一点缓冲时间
    }
}

void Voice_Init(void) {
    Voice_Speak("[d]"); // 复位提示音
    HAL_Delay(100);
}