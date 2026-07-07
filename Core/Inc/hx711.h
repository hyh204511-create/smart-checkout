/* Core/Inc/hx711.h */
#ifndef __HX711_H
#define __HX711_H

#include <stdint.h>
#include <stddef.h>
#include "stm32f4xx_hal.h"
#include "main.h"

// 抽象硬件引脚，解除与应用层的强耦合
#define HX711_SCK_PORT  GPIOB
#define HX711_SCK_PIN   GPIO_PIN_0
#define HX711_DT_PORT   GPIOB
#define HX711_DT_PIN    GPIO_PIN_1

// 提供给上层轮询的非阻塞就绪宏
#define HX711_IS_READY() (HAL_GPIO_ReadPin(HX711_DT_PORT, HX711_DT_PIN) == GPIO_PIN_RESET)

// --- 核心驱动声明 ---
void HX711_Init_Tare(void);
float HX711_Get_Weight(void);
int32_t HX711_Read_Raw(void);
int32_t HX711_Get_Offset(void);

// 工业级动态标定与校准接口
void HX711_Set_Calibration(float coef, int32_t offset);
float HX711_Get_Coef(void);
int8_t HX711_Calibrate_With_Weight(float known_weight_g);

#endif