/* Core/Src/app.c */
#include "app.h"
#include "lcd.h"
#include "voice.h"
#include "hx711.h" 
#include "keyboard.h" 
#include <string.h>
#include <stdio.h>
#include "cmsis_os.h"
#include "FreeRTOS.h"
#include "task.h"

extern UART_HandleTypeDef huart1; 
extern UART_HandleTypeDef huart3; 
extern DMA_HandleTypeDef hdma_usart1_rx;

osMutexId_t uiMutexHandle;
osMutexId_t voiceMutexHandle;
volatile uint8_t sys_init_done = 0; 

const osMutexAttr_t uiMutex_attr = { "uiMutex", osMutexRecursive | osMutexPrioInherit, NULL, 0U };
const osMutexAttr_t voiceMutex_attr = { "voiceMutex", osMutexRecursive | osMutexPrioInherit, NULL, 0U };

#define LOCK_UI()    osMutexAcquire(uiMutexHandle, osWaitForever)
#define UNLOCK_UI()  osMutexRelease(uiMutexHandle)
#define LOCK_VOICE() osMutexAcquire(voiceMutexHandle, osWaitForever)
#define UNLOCK_VOICE() osMutexRelease(voiceMutexHandle)

#define V_ZHONG_LIANG   "\xD6\xD8\xC1\xBF" 
#define V_KE            "\xBF\xCB"         
#define V_DIAN          "\xB5\xE3"         
#define V_YUAN          "\xD4\xAA"         
#define V_GONG          "\xB9\xB2"         
#define V_SHI_BIE       "\xCA\xB6\xB1\xF0\xB5\xBD" 
#define V_WELCOME       "\xBB\xB6\xD3\xAD\xCA\xB9\xD3\xC3\xD6\xC7\xC4\xDC\xBD\xE1\xCB\xE3\xCF\xB5\xCD\xB3" 

#define FRAME_HEAD_1    0xAA
#define FRAME_HEAD_2    0x55
#define FRAME_TAIL      0xFF
#define TYPE_WEIGHT     0x01
#define TYPE_INFO       0x02 

#define UART_DMA_BUF_SIZE 2048
static uint8_t g_dma_rx_buf[UART_DMA_BUF_SIZE]; 
static uint16_t g_dma_read_pos = 0;

static float current_weight = 0.0f;      
static float current_price = 0.0f;       
static char current_name[32] = {0};      
static uint32_t stable_start_time = 0;
static uint8_t is_stable = 0;
static uint8_t has_spoken = 0;

#define ABS(x) ((x) > 0 ? (x) : -(x))

static float Fast_Atof(const char* s) {
    float res = 0; int dec = 0; float div = 1.0f;
    while(*s) {
        if(*s == '.') { dec = 1; }
        else if(*s >= '0' && *s <= '9') {
            if(!dec) res = res * 10 + (*s - '0');
            else { res = res * 10 + (*s - '0'); div *= 10; }
        }
        s++;
    }
    return res / div;
}

// ====================================================================
// 动态智能滤波引擎
// ====================================================================
#define EMA_ALPHA 0.3f 
#define LOCK_THRESHOLD 2.0f 
#define FAST_JUMP_THRESHOLD 15.0f 

static float filter_val = 0.0f;
static uint8_t filter_first = 1;
static float locked_val = 0.0f;

static void Reset_Weight_Filters(void) {
    filter_first = 1;
    filter_val = 0.0f;
    locked_val = 0.0f;
    current_weight = 0.0f;
    is_stable = 0;
}

static float Base_Filter(float new_val) {
    if (filter_first) { filter_val = new_val; filter_first = 0; }
    else { 
        if (new_val > -5.0f && new_val < 5.0f) {
            filter_val = new_val;
        }
        else if (ABS(new_val - filter_val) > FAST_JUMP_THRESHOLD) {
            filter_val = new_val;
        }
        else {
            filter_val = (EMA_ALPHA * new_val) + ((1.0f - EMA_ALPHA) * filter_val); 
        }
    }
    return filter_val;
}

static float Window_Lock_Logic(float raw_filtered_val) {
    if (raw_filtered_val > -5.0f && raw_filtered_val < 5.0f) {
        locked_val = 0.0f; return 0.0f;
    }
    if (ABS(raw_filtered_val - locked_val) > LOCK_THRESHOLD) {
        locked_val = raw_filtered_val;
    }
    return locked_val;
}
// ====================================================================

static void Draw_UI_Frame(void);
static void Update_UI_Weight_And_Total(void); 
static void Update_UI_Product_Info(void);     
static void Send_Weight_To_Pi(float weight);
static void Process_RX_Buffer(void);
static void Speak_Result(void);

void Key1_Init(void) {} 
void App_Input_Task_Entry(void) { while(1) osDelay(1000); }

void Checkout_Init(void) {
    uiMutexHandle = osMutexNew(&uiMutex_attr);
    voiceMutexHandle = osMutexNew(&voiceMutex_attr);
    LCD_Init(); Draw_UI_Frame(); Voice_Init(); 
    LOCK_VOICE(); Voice_Speak(V_WELCOME); UNLOCK_VOICE();
    HAL_Delay(1000); HX711_Init_Tare(); 
    HAL_UART_Receive_DMA(&huart1, g_dma_rx_buf, UART_DMA_BUF_SIZE);
    sys_init_done = 1;
}

void Checkout_Loop(void) {
    if (sys_init_done == 0) return;

    if(huart1.ErrorCode != HAL_UART_ERROR_NONE) {
        __HAL_UART_CLEAR_OREFLAG(&huart1); __HAL_UART_CLEAR_NEFLAG(&huart1);
        __HAL_UART_CLEAR_FEFLAG(&huart1); __HAL_UART_CLEAR_PEFLAG(&huart1);
        huart1.ErrorCode = HAL_UART_ERROR_NONE; 
        HAL_UART_Receive_DMA(&huart1, g_dma_rx_buf, UART_DMA_BUF_SIZE);
        g_dma_read_pos = 0; 
    }

    float raw_w = 0.0f;
    
    // 采用宏解耦底层硬件
    if (HX711_IS_READY()) {
        raw_w = HX711_Get_Weight(); 
    } else { 
        return; 
    }

    float w_smoothed = Base_Filter(raw_w);
    float w_locked   = Window_Lock_Logic(w_smoothed);

    if (w_locked != current_weight) {
        current_weight = w_locked;
        Update_UI_Weight_And_Total(); 
        Send_Weight_To_Pi(current_weight);
        stable_start_time = HAL_GetTick();
        is_stable = 0;
    } else {
        if (is_stable == 0 && (HAL_GetTick() - stable_start_time > 800)) {
            is_stable = 1; 
        }
    }

    Process_RX_Buffer();

    if (current_weight > 10.0f && is_stable == 1 && has_spoken == 0 && current_price > 0.01f) {
        Speak_Result();
        has_spoken = 1; 
    }
    else if (current_weight < 5.0f) {
        if (has_spoken != 0 || current_price > 0.01f || current_name[0] != '\0') {
            has_spoken = 0; 
            current_price = 0.0f;
            memset(current_name, 0, sizeof(current_name));
            Update_UI_Product_Info(); 
        }
    }
}

static void Process_RX_Buffer(void) {
    uint16_t dma_write_pos = UART_DMA_BUF_SIZE - __HAL_DMA_GET_COUNTER(&hdma_usart1_rx);
    static uint8_t frame[128]; 
    while (g_dma_read_pos != dma_write_pos) {
        uint8_t b = g_dma_rx_buf[g_dma_read_pos];
        g_dma_read_pos = (g_dma_read_pos + 1) % UART_DMA_BUF_SIZE;
        
        static uint8_t state = 0;
        static uint8_t idx = 0;
        static uint8_t len = 0;
        switch(state) {
            case 0: if(b == FRAME_HEAD_1) state=1; break;
            case 1: if(b == FRAME_HEAD_2) state=2; else state=0; break;
            case 2: if(b == TYPE_INFO) state=3; else state=0; break; 
            case 3: len = b; idx = 0; state=4; break; 
            case 4: frame[idx++] = b; if(idx >= len) state = 5; break;
            case 5: state = 6; break;
            case 6: 
                if(b == FRAME_TAIL) {
                    frame[len] = '\0'; 
                    char* str = (char*)frame;
                    char* sep = strchr(str, ':');
                    
                    if(sep) {
                        *sep = '\0';
                        strcpy(current_name, str);       
                        current_price = Fast_Atof(sep + 1); 
                        
                        Update_UI_Product_Info();
                        Update_UI_Weight_And_Total();
                        has_spoken = 0; 
                    } else {
                        if (strcmp(str, "CMD_TARE") == 0) {
                            HX711_Init_Tare();        
                            Reset_Weight_Filters();   
                            Update_UI_Weight_And_Total(); 
                            Send_Weight_To_Pi(0.0f);  
                        } else {
                            LOCK_VOICE();
                            Voice_Speak("%s", str); 
                            UNLOCK_VOICE();
                        }
                    }
                }
                state = 0; break;
        }
    }
}

static void Update_UI_Weight_And_Total(void) {
    LOCK_UI();
    char buf[32];
    POINT_COLOR=BLACK; BACK_COLOR=WHITE; 
    
    // 修复当 -1 < current_weight < 0 时丢失负号的问题
    int w_int = (int)current_weight; 
    int w_dec = (int)(ABS(current_weight - (float)w_int) * 10.0f + 0.5f); // 引入四舍五入
    const char* sign = (current_weight < 0 && w_int == 0) ? "-" : "";
    
    sprintf(buf, "%s%d.%d g        ", sign, w_int, w_dec); 
    LCD_ShowString(100, 130, 200, 24, 24, buf);
    
    if(current_price > 0.01f) {
        float total = current_price * (current_weight / 1000.0f); 
        sprintf(buf, "Total: %.2f      ", total);
        LCD_ShowString(20, 210, 200, 24, 24, buf);
    }
    UNLOCK_UI();
}

static void Update_UI_Product_Info(void) {
    LOCK_UI();
    char buf[32];
    BACK_COLOR=WHITE; 
    
    if(current_price > 0.01f) {
        POINT_COLOR=RED; 
        sprintf(buf, "%-12s", current_name); 
        LCD_ShowString(20, 60, 200, 24, 24, buf); 
        
        POINT_COLOR=BLUE; 
        sprintf(buf, "Price: %.2f      ", current_price);
        LCD_ShowString(20, 90, 200, 16, 16, buf);
    } else {
        POINT_COLOR=BLACK;
        LCD_ShowString(20, 60, 200, 24, 24, "Put Item...     ");
        LCD_ShowString(20, 90, 200, 16, 16, "                ");
        LCD_ShowString(20, 210, 200, 24, 24, "                ");
    }
    UNLOCK_UI();
}

static void Speak_Result(void) {
    float total = current_price * (current_weight / 1000.0f);
    
    int total_cents = (int)(total * 100 + 0.5f);
    int t_int = total_cents / 100;
    int d1 = (total_cents % 100) / 10;
    int d2 = (total_cents % 100) % 10;
    
    LOCK_VOICE();
    Voice_Speak("[v5]%s%s[v5]%s%d%s[n2]%d%d[n1]%s", 
                V_SHI_BIE, current_name, 
                V_GONG, t_int, V_DIAN, d1, d2, V_YUAN);
    UNLOCK_VOICE();
}

static void Draw_UI_Frame(void) {
    LCD_Clear(WHITE); LCD_Fill(0,0,240,40,BLUE); 
    POINT_COLOR=WHITE; BACK_COLOR=BLUE;
    LCD_ShowString(10,10,200,24,24,"Smart Scale"); 
    POINT_COLOR=BLACK; BACK_COLOR=WHITE;
    LCD_DrawRectangle(10,50,230,120);  
    LCD_DrawRectangle(10,120,230,180); 
    LCD_ShowString(20,130,200,16,16,"Weight:"); 
    LCD_DrawRectangle(10,190,230,240); 
}

// 1. 定义静态全局发送缓冲区 
// (必须是 static 或全局变量，避免局部变量出栈被销毁导致 DMA/IT 发送乱码)
static uint8_t g_tx_buffer[8];

static void Send_Weight_To_Pi(float weight) {
    // 2. 非阻塞状态检查：如果底层 UART TX 还在忙，直接丢弃本次发送请求
    // 积压旧的重量数据没有意义，我们只关心最新的重量
    if (huart1.gState != HAL_UART_STATE_READY) {
        return; 
    }

    // 3. 数据类型转换与校验和计算
    int16_t w_int = (int16_t)(weight + 0.5f); 
    uint8_t H = (w_int >> 8) & 0xFF; 
    uint8_t L = w_int & 0xFF;
    uint8_t sum = (FRAME_HEAD_1 + FRAME_HEAD_2 + TYPE_WEIGHT + 0x02 + H + L) & 0xFF;
    
    // 4. 填充静态缓冲区
    g_tx_buffer[0] = FRAME_HEAD_1; 
    g_tx_buffer[1] = FRAME_HEAD_2; 
    g_tx_buffer[2] = TYPE_WEIGHT; 
    g_tx_buffer[3] = 0x02; 
    g_tx_buffer[4] = H; 
    g_tx_buffer[5] = L; 
    g_tx_buffer[6] = sum; 
    g_tx_buffer[7] = FRAME_TAIL;

    // 5. 发起非阻塞发送
    // 这里优先推荐使用中断发送(_IT)。因为 8 字节极小，中断开销甚至低于 DMA 的配置开销。
    // 如果你在 STM32CubeMX 中启用了 USART1_TX 的 DMA，也可以直接替换为 HAL_UART_Transmit_DMA
    HAL_UART_Transmit_IT(&huart1, g_tx_buffer, 8); 
}






