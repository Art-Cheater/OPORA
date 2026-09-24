#define F_CPU 6000000UL
#include <avr/io.h>
#include <avr/pgmspace.h>
#include <util/delay.h>
#include <stdint.h>
#include "config.h"

/*
 * IPP TCP v2.2.6 STATE SPLIT TX
 * ATmega8515 @ 6 MHz + BGS2T, UART 9600 8N1.
 *
 * Hardware kept from confirmed working branch:
 *   PC2 -> CON6, PC1 -> CON7, PC0 -> CON8, relays active LOW.
 *   cold boot: OFF/OFF/OFF.
 *   TCP/GPRS reconnect does NOT alter relay state.
 *   PD3..PD7 HIGH from startup.
 *   U2 /OE = PC4, U3 /OE = PC5, shared Port A bus.
 *
 * Security handshake remains production JSON/HMAC only during connect:
 *   GW  -> {"type":"challenge","version":"1","nonce":"..."}\n
 *   DEV -> {"type":"auth","version":"1","device_id":"...","hmac":"..."}\n
 *   GW  -> AUTHENTICATED 2\n
 *
 * AFTER authenticated there is NO JSON.
 * Text protocol:
 *   PING
 *   GET
 *   SET 6 0|1
 *   SET 7 0|1
 *   SET 8 0|1
 *   SETALL 0|1
 *
 * Replies:
 *   PONG
 *   OK 6 1
 *   OK ALL 0
 *   ERR CMD
 *   STATE O=5 U2=FF U3=A6 CSQ=20 CREG=1 CGATT=1
 *   Optional, only when con_src maps every pin of that connector:
 *   STATE O=5 U2=FF U3=A6 C9=2D C10=3F C11=15 CSQ=20 CREG=1 CGATT=1
 *
 * con_src is the only CON9/CON10/CON11 -> buffer bit table.
 * 0xFF means the Board sources do not prove that pin. Do not invent it.
 * Mapped byte: bit7 = 1 for U3, 0 for U2; bits 2..0 = buffer bit.
 * C9/C10/C11 bit0 = pin1 ... bit5 = pin6. Phase names stay on the server.
 */

#define RELAY8 PC0
#define RELAY7 PC1
#define RELAY6 PC2
#define LCD_E  PC3
#define U2_OE  PC4
#define U3_OE  PC5

#define LCD_RS PA3
#define LCD_D4 PA4
#define LCD_D5 PA5
#define LCD_D6 PA6
#define LCD_D7 PA7

#define ATBUF_N 32
#define RX_LINE_N 20

static const char device_id[] PROGMEM = DEVICE_ID_LITERAL;
static const char device_secret[] PROGMEM = DEVICE_SECRET_LITERAL;
static const char tcp_host[] PROGMEM = TCP_HOST_LITERAL;

/* Shared scratch area: AT replies or SHA block. Handshake JSON is parsed streaming. */
static union {
    char atbuf[ATBUF_N];
    uint8_t sha_block[64];
} work;
#define atbuf (work.atbuf)
#define shab  (work.sha_block)

/* nonce and digest are never needed at the same time. */
static union {
    char nonce[NONCE_MAX+1];
    uint8_t digest[32];
} auth_arg;

static uint8_t r6=0,r7=0,r8=0;
static uint8_t csq=0,net_creg=0,net_cgatt=0;
static uint8_t last_u2=0xFF,last_u3=0xFF;
static uint8_t authenticated=0;

static char rx_line[RX_LINE_N];
static uint8_t rx_len=0,rx_overflow=0;
static uint8_t pending_text_cmd=0;
static uint8_t auth_stage=0; /* 0=wait nonce, 1=auth sent, 2=authenticated */
static uint8_t auth_nonce_match=0;
static uint8_t auth_nonce_state=0; /* 0=find key, 1=colon, 2=quote, 3=value, 4=done */
static uint8_t auth_nonce_len=0;
static uint8_t auth_authenticated_match=0;
static uint8_t pending_auth_tx=0;
static uint8_t pending_initial_state=0;
static uint16_t auth_started_ms=0;

static uint16_t clock_ms=0;
static uint16_t last_state_ms=0;

static void tick_ms(void){ clock_ms++; }
static void dms(uint16_t ms){
    while(ms--){ _delay_ms(1); tick_ms(); }
}
static uint8_t elapsed_ms(uint16_t since,uint16_t interval){
    return (uint16_t)(clock_ms-since)>=interval;
}

/* ---------------- UART ---------------- */
static void uart_init(void){
    uint16_t u=(uint16_t)((F_CPU/(16UL*9600UL))-1UL);
    UCSRB=0;
    UBRRH=(uint8_t)(u>>8);
    UBRRL=(uint8_t)u;
    UCSRB=(1<<RXEN)|(1<<TXEN);
    UCSRC=(1<<URSEL)|(1<<UCSZ1)|(1<<UCSZ0);
}
static uint8_t rx_ready(void){ return (UCSRA&(1<<RXC))!=0; }
static void uart_putc(char c){ while(!(UCSRA&(1<<UDRE))); UDR=c; }
static void uart_puts_P(PGM_P p){ char c; while((c=pgm_read_byte(p++)))uart_putc(c); }
static void flush_rx(void){ while(rx_ready())(void)UDR; }

static uint8_t contains_P(const char *s,PGM_P pat){
    uint8_t i,j; char pc;
    for(i=0;s[i];i++){
        j=0;
        for(;;){
            pc=pgm_read_byte(pat+j);
            if(!pc)return 1;
            if(s[i+j]!=pc)break;
            j++;
        }
    }
    return 0;
}

static uint8_t capture(uint16_t ms){
    uint16_t t; uint8_t n=0;
    atbuf[0]=0;
    for(t=0;t<ms;t++){
        while(rx_ready()){
            uint8_t st=UCSRA,b=UDR;
            if(!(st&((1<<FE)|(1<<DOR)|(1<<PE))) && n<ATBUF_N-1){
                atbuf[n++]=(char)b;
                atbuf[n]=0;
            }
        }
        _delay_ms(1); tick_ms();
    }
    return n;
}
static void cmd_P(PGM_P p,uint16_t ms){
    flush_rx(); uart_puts_P(p); uart_putc('\r'); capture(ms);
}

/* ---------------- LCD: minimal status only ---------------- */
static void lcd_bus_out(void){
    DDRA|=(1<<LCD_RS)|(1<<LCD_D4)|(1<<LCD_D5)|(1<<LCD_D6)|(1<<LCD_D7);
    DDRC|=(1<<LCD_E);
}
static void lpulse(void){
    PORTC&=~(1<<LCD_E); _delay_us(2);
    PORTC|=(1<<LCD_E);  _delay_us(2);
    PORTC&=~(1<<LCD_E); _delay_us(70);
}
static void l4(uint8_t n){
    lcd_bus_out();
    if(n&1)PORTA|=(1<<LCD_D4);else PORTA&=~(1<<LCD_D4);
    if(n&2)PORTA|=(1<<LCD_D5);else PORTA&=~(1<<LCD_D5);
    if(n&4)PORTA|=(1<<LCD_D6);else PORTA&=~(1<<LCD_D6);
    if(n&8)PORTA|=(1<<LCD_D7);else PORTA&=~(1<<LCD_D7);
    lpulse();
}
static void lc(uint8_t c){
    PORTA&=~(1<<LCD_RS); l4(c>>4); l4(c&15);
    if(c==1||c==2)_delay_ms(3);
}
static void ld(uint8_t c){ PORTA|=(1<<LCD_RS); l4(c>>4); l4(c&15); }
static void linit1(void){
    lcd_bus_out(); PORTC&=~(1<<LCD_E); PORTA&=~(1<<LCD_RS); _delay_ms(60);
    l4(3);_delay_ms(6);l4(3);_delay_ms(2);l4(3);_delay_ms(2);l4(2);
    lc(0x28);lc(0x08);lc(1);lc(0x06);lc(0x0C);
}
static void linit(void){
    PORTC|=(1<<U2_OE)|(1<<U3_OE);
    DDRC|=(1<<U2_OE)|(1<<U3_OE)|(1<<LCD_E);
    PORTC&=(uint8_t)~(1<<LCD_E);
    PORTA&=(uint8_t)~((1<<LCD_RS)|(1<<LCD_D4)|(1<<LCD_D5)|(1<<LCD_D6)|(1<<LCD_D7));
    DDRA|=(1<<LCD_RS)|(1<<LCD_D4)|(1<<LCD_D5)|(1<<LCD_D6)|(1<<LCD_D7);
    _delay_ms(300); linit1(); _delay_ms(100); linit1();
}
static void lline_P(uint8_t row,PGM_P p){
    uint8_t i=0; char c;
    lc((uint8_t)(0x80|(row?0x40:0)));
    while(i<16 && (c=pgm_read_byte(p++))){ld(c);i++;}
    while(i++<16)ld(' ');
}
static void screen_P(PGM_P a,PGM_P b){ lc(1); lline_P(0,a); lline_P(1,b); }
static void screen_e6(uint8_t n){
    uint8_t i;
    lc(1); lline_P(0,PSTR("E06 TCP")); lc(0xC0);
    ld('E'); ld('6'); ld((uint8_t)('0'+n));
    for(i=3;i<16;i++)ld(' ');
}

/* ---------------- Confirmed shared-bus RAW inputs ---------------- */
static void buffers_disable(void){ PORTC|=(1<<U2_OE)|(1<<U3_OE); }
static void shared_bus_input(void){ DDRA=0x00; PORTA=0x00; }
static void restore_lcd_bus(void){ buffers_disable(); lcd_bus_out(); }
static uint8_t read_u2(void){
    uint8_t v;
    buffers_disable(); shared_bus_input();
    PORTC&=(uint8_t)~(1<<U2_OE); _delay_us(5); v=PINA; PORTC|=(1<<U2_OE);
    restore_lcd_bus(); return v;
}
static uint8_t read_u3(void){
    uint8_t v;
    buffers_disable(); shared_bus_input();
    PORTC&=(uint8_t)~(1<<U3_OE); _delay_us(5); v=PINA; PORTC|=(1<<U3_OE);
    restore_lcd_bus(); return v;
}
static uint8_t raw_inputs_changed(void){
    uint8_t u2=read_u2(),u3=read_u3();
    if(u2==last_u2 && u3==last_u3)return 0;
#if INPUT_DEBOUNCE_MS > 0
    dms(INPUT_DEBOUNCE_MS);
    {
        uint8_t u2b=read_u2(),u3b=read_u3();
        if(u2b!=u2 || u3b!=u3)return 0;
        u2=u2b; u3=u3b;
    }
#endif
    last_u2=u2; last_u3=u3;
    return 1;
}

/* ---------------- Relays ---------------- */
static void relays_off(void){
    PORTC|=(1<<RELAY6)|(1<<RELAY7)|(1<<RELAY8);
    r6=r7=r8=0;
}
static void apply_relays(void){
    if(r6)PORTC&=~(1<<RELAY6);else PORTC|=(1<<RELAY6);
    if(r7)PORTC&=~(1<<RELAY7);else PORTC|=(1<<RELAY7);
    if(r8)PORTC&=~(1<<RELAY8);else PORTC|=(1<<RELAY8);
}

/* ---------------- SRAM-compact SHA-256 / HMAC ---------------- */
typedef struct { uint32_t h[8]; uint16_t bits; uint8_t n; } sha256_t;
static sha256_t sha_ctx;
static const uint32_t K[64] PROGMEM={
0x428a2f98UL,0x71374491UL,0xb5c0fbcfUL,0xe9b5dba5UL,0x3956c25bUL,0x59f111f1UL,0x923f82a4UL,0xab1c5ed5UL,
0xd807aa98UL,0x12835b01UL,0x243185beUL,0x550c7dc3UL,0x72be5d74UL,0x80deb1feUL,0x9bdc06a7UL,0xc19bf174UL,
0xe49b69c1UL,0xefbe4786UL,0x0fc19dc6UL,0x240ca1ccUL,0x2de92c6fUL,0x4a7484aaUL,0x5cb0a9dcUL,0x76f988daUL,
0x983e5152UL,0xa831c66dUL,0xb00327c8UL,0xbf597fc7UL,0xc6e00bf3UL,0xd5a79147UL,0x06ca6351UL,0x14292967UL,
0x27b70a85UL,0x2e1b2138UL,0x4d2c6dfcUL,0x53380d13UL,0x650a7354UL,0x766a0abbUL,0x81c2c92eUL,0x92722c85UL,
0xa2bfe8a1UL,0xa81a664bUL,0xc24b8b70UL,0xc76c51a3UL,0xd192e819UL,0xd6990624UL,0xf40e3585UL,0x106aa070UL,
0x19a4c116UL,0x1e376c08UL,0x2748774cUL,0x34b0bcb5UL,0x391c0cb3UL,0x4ed8aa4aUL,0x5b9cca4fUL,0x682e6ff3UL,
0x748f82eeUL,0x78a5636fUL,0x84c87814UL,0x8cc70208UL,0x90befffaUL,0xa4506cebUL,0xbef9a3f7UL,0xc67178f2UL};
#define ROR(x,n) (((x)>>(n))|((x)<<(32-(n))))
static uint32_t blk_get(uint8_t i){
    uint8_t o=(uint8_t)(i<<2);
    return ((uint32_t)shab[o]<<24)|((uint32_t)shab[o+1]<<16)|((uint32_t)shab[o+2]<<8)|shab[o+3];
}
static void blk_set(uint8_t i,uint32_t v){
    uint8_t o=(uint8_t)(i<<2);
    shab[o]=(uint8_t)(v>>24);shab[o+1]=(uint8_t)(v>>16);shab[o+2]=(uint8_t)(v>>8);shab[o+3]=(uint8_t)v;
}
static void sha_block(void){
    uint32_t a,b,c,d,e,f,g,h,t1,t2,w,x,y; uint8_t i,q;
    a=sha_ctx.h[0];b=sha_ctx.h[1];c=sha_ctx.h[2];d=sha_ctx.h[3];
    e=sha_ctx.h[4];f=sha_ctx.h[5];g=sha_ctx.h[6];h=sha_ctx.h[7];
    for(i=0;i<64;i++){
        if(i<16)w=blk_get(i);
        else{
            q=(uint8_t)(i&15);x=blk_get((uint8_t)((i-15)&15));y=blk_get((uint8_t)((i-2)&15));
            w=blk_get(q)+(ROR(x,7)^ROR(x,18)^(x>>3))+blk_get((uint8_t)((i-7)&15))+(ROR(y,17)^ROR(y,19)^(y>>10));
            blk_set(q,w);
        }
        t1=h+(ROR(e,6)^ROR(e,11)^ROR(e,25))+((e&f)^((~e)&g))+pgm_read_dword(&K[i])+w;
        t2=(ROR(a,2)^ROR(a,13)^ROR(a,22))+((a&b)^(a&c)^(b&c));
        h=g;g=f;f=e;e=d+t1;d=c;c=b;b=a;a=t1+t2;
    }
    sha_ctx.h[0]+=a;sha_ctx.h[1]+=b;sha_ctx.h[2]+=c;sha_ctx.h[3]+=d;
    sha_ctx.h[4]+=e;sha_ctx.h[5]+=f;sha_ctx.h[6]+=g;sha_ctx.h[7]+=h;
}
static void sha_init(void){
    sha_ctx.h[0]=0x6a09e667UL;sha_ctx.h[1]=0xbb67ae85UL;sha_ctx.h[2]=0x3c6ef372UL;sha_ctx.h[3]=0xa54ff53aUL;
    sha_ctx.h[4]=0x510e527fUL;sha_ctx.h[5]=0x9b05688cUL;sha_ctx.h[6]=0x1f83d9abUL;sha_ctx.h[7]=0x5be0cd19UL;
    sha_ctx.bits=0;sha_ctx.n=0;
}
static void sha_byte(uint8_t v){
    shab[sha_ctx.n++]=v;sha_ctx.bits=(uint16_t)(sha_ctx.bits+8);
    if(sha_ctx.n==64){sha_block();sha_ctx.n=0;}
}
static void sha_ram(const char *s){while(*s)sha_byte((uint8_t)*s++);}
static void sha_pgm(PGM_P p){char c;while((c=pgm_read_byte(p++)))sha_byte((uint8_t)c);}
static void sha_final(uint8_t *out){
    uint8_t i;uint16_t bits=sha_ctx.bits;
    shab[sha_ctx.n++]=0x80;
    if(sha_ctx.n>56){while(sha_ctx.n<64)shab[sha_ctx.n++]=0;sha_block();sha_ctx.n=0;}
    while(sha_ctx.n<62)shab[sha_ctx.n++]=0;
    shab[62]=(uint8_t)(bits>>8);shab[63]=(uint8_t)bits;sha_block();
    for(i=0;i<8;i++){
        out[i*4]=(uint8_t)(sha_ctx.h[i]>>24);out[i*4+1]=(uint8_t)(sha_ctx.h[i]>>16);
        out[i*4+2]=(uint8_t)(sha_ctx.h[i]>>8);out[i*4+3]=(uint8_t)sha_ctx.h[i];
    }
}
static uint8_t secret_len(void){uint8_t n=0;while(pgm_read_byte(device_secret+n))n++;return n;}
static void hmac_make(void){
    uint8_t i,n=secret_len(),v;
    sha_init();
    for(i=0;i<64;i++){v=(i<n)?pgm_read_byte(device_secret+i):0;sha_byte((uint8_t)(v^0x36));}
    sha_pgm(device_id);sha_byte(':');sha_ram(auth_arg.nonce);sha_final(auth_arg.digest);
    sha_init();
    for(i=0;i<64;i++){v=(i<n)?pgm_read_byte(device_secret+i):0;sha_byte((uint8_t)(v^0x5c));}
    for(i=0;i<32;i++)sha_byte(auth_arg.digest[i]);
    sha_final(auth_arg.digest);
}

/* ---------------- BGS2T TX: one frame = one SISW ---------------- */
static uint8_t pgm_len(PGM_P p){uint8_t n=0;while(pgm_read_byte(p+n))n++;return n;}
static void put_u16_dec(uint16_t v){
    char tmp[5];uint8_t n=0;
    if(v==0){uart_putc('0');return;}
    while(v&&n<5){tmp[n++]=(char)('0'+v%10);v/=10;}
    while(n)uart_putc(tmp[--n]);
}
static uint8_t dec_len_u8(uint8_t v){return v>=100?3:(v>=10?2:1);}
static int16_t sisw_confirmed_len(void){
    uint8_t i=0;
    int16_t v=0;
    PGM_P p=PSTR("^SISW: 0,");

    while(atbuf[i]){
        uint8_t j=0,k=i;

        while(pgm_read_byte(p+j) && atbuf[k]==pgm_read_byte(p+j)){
            j++;k++;
        }

        if(!pgm_read_byte(p+j)){
            while(atbuf[k]==' '||atbuf[k]=='\t')k++;

            if(atbuf[k]<'0'||atbuf[k]>'9')return -1;

            while(atbuf[k]>='0'&&atbuf[k]<='9'){
                v=(int16_t)(v*10+(atbuf[k]-'0'));
                k++;
            }
            return v;
        }

        i++;
    }

    return -1;
}

static uint8_t socket_frame_begin(uint16_t len){
    uint8_t tries;
    int16_t cnf;

    /*
     * BGS2T uses cnfWriteLength as flow control.
     * ^SISW: 0,0,... means "cannot write now", NOT a dead socket.
     * In polling mode retry until the modem grants the requested frame.
     *
     * We keep the project rule ONE APP FRAME = ONE SISW:
     * only an exact grant for the complete short frame is accepted.
     */
    for(tries=0;tries<SISW_READY_RETRIES;tries++){
        flush_rx();
        uart_puts_P(PSTR("AT^SISW=0,"));
        put_u16_dec(len);
        uart_putc('\r');

        capture(SISW_READY_TIMEOUT_MS);

        if(contains_P(atbuf,PSTR("ERROR")) ||
           contains_P(atbuf,PSTR("+CME ERROR"))){
            dms(SISW_RETRY_DELAY_MS);
            continue;
        }

        cnf=sisw_confirmed_len();

        if(cnf==(int16_t)len)return 1;

        if(cnf==0 || cnf<0){
            dms(SISW_RETRY_DELAY_MS);
            continue;
        }

        /*
         * Positive partial binary grant would require sending exactly cnf bytes,
         * which would split an application frame. Abort this socket instead of
         * violating protocol framing.
         */
        screen_P(PSTR("E12 TX"),PSTR("PART"));
        return 0;
    }

    screen_P(PSTR("E12 TX"),PSTR("BUSY"));
    return 0;
}

static uint8_t socket_frame_finish(void){
    capture(SISW_FINISH_TIMEOUT_MS);

    if(contains_P(atbuf,PSTR("ERROR")) ||
       contains_P(atbuf,PSTR("+CME ERROR")))return 0;

    /*
     * BGS2T returns OK when the binary write cycle has accepted the bytes.
     * Require the explicit completion instead of treating an empty timeout
     * as success.
     */
    return contains_P(atbuf,PSTR("OK"));
}

static uint8_t send_P(PGM_P p){
    uint8_t n=pgm_len(p);if(!socket_frame_begin(n))return 0;uart_puts_P(p);return socket_frame_finish();
}
static void put_hex2(uint8_t v){
    static const char hx[] PROGMEM="0123456789ABCDEF";
    uart_putc((char)pgm_read_byte(hx+(v>>4)));uart_putc((char)pgm_read_byte(hx+(v&15)));
}

static uint8_t send_auth(void){
    /*
     * IMPORTANT:
     * AUTH is one logical TCP JSON line, but BGS2T is allowed to receive it
     * through several small SISW writes. TCP reassembles these bytes in order.
     *
     * This deliberately returns to the transport style that previously reached
     * production authentication reliably, while keeping the v2 ASCII protocol
     * after authentication.
     */
    static const char hx[] PROGMEM="0123456789abcdef";
    PGM_P a=PSTR("{\"type\":\"auth\",\"version\":\"1\",\"device_id\":\"");
    PGM_P b=PSTR("\",\"hmac\":\"");
    PGM_P c=PSTR("\"}\n");
    uint8_t block,i,v;

    hmac_make();

    screen_P(PSTR("AUTH"),PSTR("TX"));

    if(!send_P(a))return 0;
    if(!send_P(device_id))return 0;
    if(!send_P(b))return 0;

    /* 64 hex chars in four small 16-byte modem writes. */
    for(block=0;block<4;block++){
        if(!socket_frame_begin(16))return 0;
        for(i=0;i<8;i++){
            v=auth_arg.digest[(uint8_t)(block*8+i)];
            uart_putc((char)pgm_read_byte(hx+(v>>4)));
            uart_putc((char)pgm_read_byte(hx+(v&15)));
        }
        if(!socket_frame_finish())return 0;
    }

    if(!send_P(c))return 0;

    screen_P(PSTR("AUTH"),PSTR("WAIT"));
    return 1;
}

/*
 * Only CON9/CON10/CON11 -> U2/U3 map.
 * 0xFF = Board files do not prove this pin. Do not guess.
 * Otherwise bit7 selects U3 (1) or U2 (0), bits 2..0 are the buffer bit.
 * A mask is compiled in only when all six pins of that connector are filled.
 */
#define UNMAPPED 0xFF
#define CON_PIN_UNMAPPED UNMAPPED
/* SRC is U2 or U3, BIT is 0..7. Both stay UNMAPPED until a measured net exists. */
#define CON9_1_SRC UNMAPPED
#define CON9_1_BIT UNMAPPED
#define CON9_2_SRC UNMAPPED
#define CON9_2_BIT UNMAPPED
#define CON9_3_SRC UNMAPPED
#define CON9_3_BIT UNMAPPED
#define CON9_4_SRC UNMAPPED
#define CON9_4_BIT UNMAPPED
#define CON9_5_SRC UNMAPPED
#define CON9_5_BIT UNMAPPED
#define CON9_6_SRC UNMAPPED
#define CON9_6_BIT UNMAPPED
#define CON10_1_SRC UNMAPPED
#define CON10_1_BIT UNMAPPED
#define CON10_2_SRC UNMAPPED
#define CON10_2_BIT UNMAPPED
#define CON10_3_SRC UNMAPPED
#define CON10_3_BIT UNMAPPED
#define CON10_4_SRC UNMAPPED
#define CON10_4_BIT UNMAPPED
#define CON10_5_SRC UNMAPPED
#define CON10_5_BIT UNMAPPED
#define CON10_6_SRC UNMAPPED
#define CON10_6_BIT UNMAPPED
#define CON11_1_SRC UNMAPPED
#define CON11_1_BIT UNMAPPED
#define CON11_2_SRC UNMAPPED
#define CON11_2_BIT UNMAPPED
#define CON11_3_SRC UNMAPPED
#define CON11_3_BIT UNMAPPED
#define CON11_4_SRC UNMAPPED
#define CON11_4_BIT UNMAPPED
#define CON11_5_SRC UNMAPPED
#define CON11_5_BIT UNMAPPED
#define CON11_6_SRC UNMAPPED
#define CON11_6_BIT UNMAPPED
#define CON9_1 CON_PIN_UNMAPPED
#define CON9_2 CON_PIN_UNMAPPED
#define CON9_3 CON_PIN_UNMAPPED
#define CON9_4 CON_PIN_UNMAPPED
#define CON9_5 CON_PIN_UNMAPPED
#define CON9_6 CON_PIN_UNMAPPED
#define CON10_1 CON_PIN_UNMAPPED
#define CON10_2 CON_PIN_UNMAPPED
#define CON10_3 CON_PIN_UNMAPPED
#define CON10_4 CON_PIN_UNMAPPED
#define CON10_5 CON_PIN_UNMAPPED
#define CON10_6 CON_PIN_UNMAPPED
#define CON11_1 CON_PIN_UNMAPPED
#define CON11_2 CON_PIN_UNMAPPED
#define CON11_3 CON_PIN_UNMAPPED
#define CON11_4 CON_PIN_UNMAPPED
#define CON11_5 CON_PIN_UNMAPPED
#define CON11_6 CON_PIN_UNMAPPED
#define CON_READY(a,b,c,d,e,f) ((a)!=0xFF&&(b)!=0xFF&&(c)!=0xFF&&(d)!=0xFF&&(e)!=0xFF&&(f)!=0xFF)
#define PHASE_BIT(src,u2,u3) ((uint8_t)(((((src)&0x80)?(u3):(u2))>>((src)&7))&1))
#define PHASE6(a,b,c,d,e,f,u2,u3) ((uint8_t)((PHASE_BIT(a,u2,u3)<<0)|(PHASE_BIT(b,u2,u3)<<1)|(PHASE_BIT(c,u2,u3)<<2)|(PHASE_BIT(d,u2,u3)<<3)|(PHASE_BIT(e,u2,u3)<<4)|(PHASE_BIT(f,u2,u3)<<5)))
static uint8_t send_state(void){
    PGM_P a=PSTR("STATE O=");
    PGM_P b=PSTR(" U2=");
    PGM_P c=PSTR(" U3=");
    PGM_P d=PSTR(" CSQ=");
    PGM_P e=PSTR(" CREG=");
    PGM_P f=PSTR(" CGATT=");
    uint8_t o=(uint8_t)((r6<<2)|(r7<<1)|r8);
    uint8_t u2=read_u2(),u3=read_u3();
    uint8_t n1=(uint8_t)(pgm_len(a)+1+pgm_len(b)+2+pgm_len(c)+2);
    uint8_t n2=(uint8_t)(pgm_len(d)+dec_len_u8(csq)+pgm_len(e)+
                         dec_len_u8(net_creg)+pgm_len(f)+2);

    last_u2=u2;last_u3=u3;

    /*
     * BGS2T gave a partial grant for the ~45 byte STATE frame.
     * Keep STATE one TCP line, but feed it to the modem in two short SISW writes.
     * TCP concatenates both writes without inserting anything between them.
     */
    if(!socket_frame_begin(n1))return 0;
    uart_puts_P(a);uart_putc((char)('0'+o));
    uart_puts_P(b);put_hex2(u2);
    uart_puts_P(c);put_hex2(u3);
    if(!socket_frame_finish())return 0;
#if CON_READY(CON9_1,CON9_2,CON9_3,CON9_4,CON9_5,CON9_6)
    if(!socket_frame_begin(6))return 0;
    uart_puts_P(PSTR(" C9="));put_hex2(PHASE6(CON9_1,CON9_2,CON9_3,CON9_4,CON9_5,CON9_6,u2,u3));
    if(!socket_frame_finish())return 0;
#endif
#if CON_READY(CON10_1,CON10_2,CON10_3,CON10_4,CON10_5,CON10_6)
    if(!socket_frame_begin(7))return 0;
    uart_puts_P(PSTR(" C10="));put_hex2(PHASE6(CON10_1,CON10_2,CON10_3,CON10_4,CON10_5,CON10_6,u2,u3));
    if(!socket_frame_finish())return 0;
#endif
#if CON_READY(CON11_1,CON11_2,CON11_3,CON11_4,CON11_5,CON11_6)
    if(!socket_frame_begin(7))return 0;
    uart_puts_P(PSTR(" C11="));put_hex2(PHASE6(CON11_1,CON11_2,CON11_3,CON11_4,CON11_5,CON11_6,u2,u3));
    if(!socket_frame_finish())return 0;
#endif

    if(!socket_frame_begin(n2))return 0;
    uart_puts_P(d);put_u16_dec(csq);
    uart_puts_P(e);put_u16_dec(net_creg);
    uart_puts_P(f);uart_putc((char)('0'+net_cgatt));
    uart_putc('\n');
    if(!socket_frame_finish())return 0;

    last_state_ms=clock_ms;
    return 1;
}
static uint8_t send_ok_one(uint8_t ch,uint8_t val){
    PGM_P a=PSTR("OK ");PGM_P b=PSTR(" \n");
    uint8_t len=(uint8_t)(pgm_len(a)+1+pgm_len(b));
    if(!socket_frame_begin(len))return 0;
    uart_puts_P(a);uart_putc((char)('0'+ch));uart_putc(' ');uart_putc((char)('0'+val));uart_putc('\n');
    return socket_frame_finish();
}
static uint8_t send_ok_all(uint8_t val){
    if(val)return send_P(PSTR("OK ALL 1\n"));
    return send_P(PSTR("OK ALL 0\n"));
}

/* ---------------- Continuous handshake token scanner ---------------- */
/*
 * Do NOT parse JSON objects at all.
 *
 * Before authentication we only need two tokens from the gateway stream:
 *   "nonce" : "<value>"
 *   AUTHENTICATED
 *
 * Modem framing, CR/LF, SISR chunking and unrelated JSON objects are ignored.
 * As soon as a complete nonce value is captured, AUTH is queued and sent only
 * after the current SISR transaction has drained.
 */
static void auth_scan_reset(void){
    auth_nonce_match=0;
    auth_nonce_state=0;
    auth_nonce_len=0;
    auth_authenticated_match=0;
    auth_arg.nonce[0]=0;
}

static uint8_t auth_scan_authenticated(char c){
    /*
     * Production v2 gateway response observed on wire:
     *   AUTHENTICATED 2\n
     *
     * Match only the stable word AUTHENTICATED. This also survives
     * a future protocol-number change and costs no extra buffering.
     */
    static const char pat[] PROGMEM="AUTHENTICATED";
    char want=pgm_read_byte(&pat[auth_authenticated_match]);

    if(c==want){
        auth_authenticated_match++;
        if(pgm_read_byte(&pat[auth_authenticated_match])==0){
            auth_authenticated_match=0;
            return 1;
        }
    }else{
        auth_authenticated_match=(c=='A')?1:0;
    }
    return 0;
}

static uint8_t auth_scan_nonce(char c){
    static const char key[] PROGMEM="\"nonce\"";

    if(auth_nonce_state==4)return 1;

    if(auth_nonce_state==0){
        char want=pgm_read_byte(&key[auth_nonce_match]);
        if(c==want){
            auth_nonce_match++;
            if(pgm_read_byte(&key[auth_nonce_match])==0){
                auth_nonce_match=0;
                auth_nonce_state=1;
            }
        }else{
            auth_nonce_match=(c=='\"')?1:0;
        }
        return 1;
    }

    if(auth_nonce_state==1){
        if(c==' '||c=='\t'||c=='\r'||c=='\n')return 1;
        if(c==':'){auth_nonce_state=2;return 1;}

        /* False key-like match: resume scanning instead of killing session. */
        auth_nonce_state=0;
        auth_nonce_match=(c=='\"')?1:0;
        return 1;
    }

    if(auth_nonce_state==2){
        if(c==' '||c=='\t'||c=='\r'||c=='\n')return 1;
        if(c=='\"'){
            auth_nonce_state=3;
            auth_nonce_len=0;
            return 1;
        }

        auth_nonce_state=0;
        auth_nonce_match=(c=='\"')?1:0;
        return 1;
    }

    if(auth_nonce_state==3){
        if(c=='\"'){
            if(auth_nonce_len==0){
                auth_nonce_state=0;
                return 1;
            }
            auth_arg.nonce[auth_nonce_len]=0;
            auth_nonce_state=4;
            pending_auth_tx=1;
            screen_P(PSTR("AUTH"),PSTR("NONCE OK"));
            return 1;
        }

        if(auth_nonce_len>=NONCE_MAX){
            screen_P(PSTR("E08 AUTH"),PSTR("NONCE"));
            dms(2500);
            return 0;
        }

        auth_arg.nonce[auth_nonce_len++]=c;
    }

    return 1;
}

static uint8_t auth_feed(char c){
    if(auth_scan_authenticated(c)){
        authenticated=1;
        auth_stage=2;
        pending_initial_state=1;
        screen_P(PSTR("ONLINE"),PSTR("AUTH"));
        rx_len=0;
        rx_overflow=0;
        last_u2=read_u2();
        last_u3=read_u3();
        return 1;
    }

    return auth_scan_nonce(c);
}

/* ---------------- Minimal text command parser ---------------- */
static uint8_t line_eq_P(const char *s,PGM_P p){
    char c;while((c=pgm_read_byte(p++))){if(*s++!=c)return 0;}return *s==0;
}
static uint8_t process_command(void){
    uint8_t ch,val;
    if(line_eq_P(rx_line,PSTR("PING")))return send_P(PSTR("PONG\n"));
    if(line_eq_P(rx_line,PSTR("GET")))return send_state();

    if(rx_line[0]=='S'&&rx_line[1]=='E'&&rx_line[2]=='T'&&rx_line[3]==' '&&
       (rx_line[4]=='6'||rx_line[4]=='7'||rx_line[4]=='8')&&rx_line[5]==' '&&
       (rx_line[6]=='0'||rx_line[6]=='1')&&rx_line[7]==0){
        ch=(uint8_t)(rx_line[4]-'0');val=(uint8_t)(rx_line[6]-'0');
        if(ch==6)r6=val;else if(ch==7)r7=val;else r8=val;
        apply_relays();
        if(!send_ok_one(ch,val))return 0;
        return send_state();
    }

    if(rx_line[0]=='S'&&rx_line[1]=='E'&&rx_line[2]=='T'&&rx_line[3]=='A'&&
       rx_line[4]=='L'&&rx_line[5]=='L'&&rx_line[6]==' '&&
       (rx_line[7]=='0'||rx_line[7]=='1')&&rx_line[8]==0){
        val=(uint8_t)(rx_line[7]-'0');
        r6=val;r7=val;r8=val;
        apply_relays(); /* exactly once */
        if(!send_ok_all(val))return 0;
        return send_state();
    }

    return send_P(PSTR("ERR CMD\n"));
}
static uint8_t text_feed(char c){
    if(c=='\r')return 1;

    if(c=='\n'){
        /*
         * Critical rule:
         * never call process_command() from inside AT^SISR receive processing.
         * process_command() can issue AT^SISW, which would interleave a new AT
         * command before the SISR transaction has fully drained.
         */
        if(!rx_overflow && rx_len){
            rx_line[rx_len]=0;
            pending_text_cmd=1;
        }else{
            rx_len=0;
            rx_overflow=0;
        }
        return 1;
    }

    /*
     * Only one line may be pending at a time.
     * Main processes it immediately after SISR is drained, before next read.
     */
    if(pending_text_cmd)return 1;

    if(rx_overflow)return 1;

    if(rx_len<RX_LINE_N-1){
        rx_line[rx_len++]=c;
    }else{
        rx_overflow=1;
    }

    return 1;
}

static uint8_t process_pending_text_command(void){
    uint8_t ok;

    if(!pending_text_cmd)return 1;

    pending_text_cmd=0;
    ok=process_command();
    rx_len=0;
    rx_overflow=0;
    return ok;
}

/* ---------------- BGS2T socket ---------------- */
static uint8_t socket_open(void){
    uint8_t i;

    cmd_P(PSTR("AT^SISC=0"),600);

    cmd_P(PSTR("AT^SISS=0,srvType,Socket"),1200);
    if(!contains_P(atbuf,PSTR("OK")))return 1;

    cmd_P(PSTR("AT^SISS=0,conId,0"),1200);
    if(!contains_P(atbuf,PSTR("OK")))return 2;

    flush_rx();
    uart_puts_P(PSTR("AT^SISS=0,address,\"socktcp://"));
    uart_puts_P(tcp_host);
    uart_puts_P(PSTR(":" TCP_PORT_LITERAL "\"\r"));
    capture(1500);
    if(!contains_P(atbuf,PSTR("OK")))return 3;

    cmd_P(PSTR("AT^SISO=0"),2500);
    if(!contains_P(atbuf,PSTR("OK")))return 4;

    /*
     * BGS2T polling mode:
     * AT^SISO returning OK does NOT prove the TCP session is already Up.
     * Poll AT^SISI=0 until srvState=4 before the first AT^SISR.
     */
    screen_P(PSTR("TCP"),PSTR("WAIT UP"));
    for(i=0;i<20;i++){
        cmd_P(PSTR("AT^SISI=0"),700);

        if(contains_P(atbuf,PSTR("^SISI: 0,4,")) ||
           contains_P(atbuf,PSTR("^SISI:0,4,"))){
            return 0;
        }

        /* state 6 = Down / failed */
        if(contains_P(atbuf,PSTR("^SISI: 0,6,")) ||
           contains_P(atbuf,PSTR("^SISI:0,6,"))){
            return 5;
        }

        dms(250);
    }

    return 6;
}
static void socket_close(void){cmd_P(PSTR("AT^SISC=0"),700);}
static uint8_t socket_read_once(void){
    static const char hdr[] PROGMEM="^SISR: 0,";
    uint16_t t=0;
    uint16_t payload_len=0;
    uint16_t payload_got=0;
    uint8_t hm=0;
    uint8_t state=0; /* 0=find header, 1=parse length, 2=skip header line, 3=payload, 4=drain */
    uint8_t neg=0;
    uint8_t saw_any=0;
    uint8_t quiet=0;

    /*
     * BGS2T polling-mode response is framed:
     *   ^SISR: 0,<cnfReadLength>[,<remaining>]\r\n
     *   <exactly cnfReadLength payload bytes>
     *
     * Do NOT feed modem header bytes into the TCP parser and do NOT stop on an
     * arbitrary 20 ms pause before the announced payload length is consumed.
     */
    uart_puts_P(PSTR("AT^SISR=0,128\r"));

    while(t<SISR_WAIT_MAX_MS){
        uint8_t got=0;

        while(rx_ready()){
            uint8_t st=UCSRA;
            char c=(char)UDR;
            got=1;
            saw_any=1;

            if(st&((1<<FE)|(1<<DOR)|(1<<PE)))continue;

            if(state==0){
                char want=pgm_read_byte(&hdr[hm]);
                if(c==want){
                    hm++;
                    if(pgm_read_byte(&hdr[hm])==0){
                        state=1;
                        payload_len=0;
                        neg=0;
                    }
                }else{
                    hm=(c=='^')?1:0;
                }
            }else if(state==1){
                if(c=='-'){
                    neg=1;
                }else if(c>='0'&&c<='9'){
                    payload_len=(uint16_t)(payload_len*10U+(uint16_t)(c-'0'));
                }else if(c==',' || c=='\r' || c=='\n'){
                    /* Negative values mean no normal payload for our socket use. */
                    if(neg)payload_len=0;
                    state=2;

                    /* If separator itself is LF, header line is already done. */
                    if(c=='\n'){
                        if(payload_len)state=3;
                        else state=4;
                    }
                }
            }else if(state==2){
                /* Ignore remaining header fields until LF. */
                if(c=='\n'){
                    if(payload_len)state=3;
                    else state=4;
                }
            }else if(state==3){
                if(authenticated){
                    if(!text_feed(c))return 0;
                }else{
                    if(!auth_feed(c))return 0;
                }

                payload_got++;
                if(payload_got>=payload_len){
                    state=4;
                    quiet=0;
                }
            }else{
                /* Drain trailing modem CR/LF/OK, never feed them to TCP parser. */
            }
        }

        if(got){
            quiet=0;
        }else if(state==4 && saw_any){
            /*
             * Payload count has already been satisfied. A short silence is now
             * safe because no TCP payload byte remains outstanding.
             */
            if(++quiet>=15U)break;
        }

        _delay_ms(1);
        tick_ms();
        t++;
    }

    /*
     * Timeout while an announced payload was only partially received is a real
     * transport failure. Do not issue another AT command into the unfinished reply.
     */
    if(state==3 && payload_got<payload_len){
        screen_P(PSTR("E11 RX"),PSTR("SHORT"));
        return 0;
    }

    return 1;
}

/* ---------------- GPRS init ---------------- */
static uint8_t wait_ok(PGM_P cmd,uint16_t wait,uint8_t tries){
    uint8_t i;for(i=0;i<tries;i++){cmd_P(cmd,wait);if(contains_P(atbuf,PSTR("OK")))return 1;dms(1000);}return 0;
}
static uint8_t modem_gprs_init(void){
    uint8_t i,q;
    net_creg=0;net_cgatt=0;csq=0;uart_init();screen_P(PSTR("NET"),PSTR(""));dms(6000);
    if(!wait_ok(PSTR("AT"),1000,12))return 0;
    cmd_P(PSTR("ATE0"),1000);cmd_P(PSTR("AT^SCFG=\"Tcp/WithURCs\",\"off\""),1500);
    for(i=0;i<15;i++){cmd_P(PSTR("AT+CPIN?"),1500);if(contains_P(atbuf,PSTR("READY")))break;dms(2000);}if(i==15)return 0;
    for(i=0;i<30;i++){
        cmd_P(PSTR("AT+CREG?"),1500);
        if(contains_P(atbuf,PSTR("0,1"))){net_creg=1;break;}
        if(contains_P(atbuf,PSTR("0,5"))){net_creg=5;break;}
        dms(2000);
    }
    if(i==30)return 0;
    cmd_P(PSTR("AT+CGATT=1"),5000);
    for(i=0;i<15;i++){
        cmd_P(PSTR("AT+CGATT?"),1500);
        if(contains_P(atbuf,PSTR("+CGATT: 1"))||contains_P(atbuf,PSTR("+CGATT:1"))){net_cgatt=1;break;}
        dms(2000);
    }
    if(i==15)return 0;
    cmd_P(PSTR("AT^SICS=0,conType,GPRS0"),1500);if(!contains_P(atbuf,PSTR("OK")))return 0;
    cmd_P(PSTR("AT^SICS=0,apn,\"" GPRS_APN_LITERAL "\""),1500);if(!contains_P(atbuf,PSTR("OK")))return 0;
    cmd_P(PSTR("AT^SICS=0,user,\"" GPRS_USER_LITERAL "\""),1500);if(!contains_P(atbuf,PSTR("OK")))return 0;
    cmd_P(PSTR("AT^SICS=0,passwd,\"" GPRS_PASS_LITERAL "\""),1500);if(!contains_P(atbuf,PSTR("OK")))return 0;
    cmd_P(PSTR("AT^SICS=0,inactTO,120"),1500);
    cmd_P(PSTR("AT+CSQ"),1200);
    for(q=0;q+5<ATBUF_N&&atbuf[q];q++){
        if(atbuf[q]=='+'&&atbuf[q+1]=='C'&&atbuf[q+2]=='S'&&atbuf[q+3]=='Q'&&atbuf[q+4]==':'){
            q+=5;while(q<ATBUF_N&&(atbuf[q]==' '||atbuf[q]==':'))q++;
            if(q<ATBUF_N&&atbuf[q]>='0'&&atbuf[q]<='9'){
                csq=(uint8_t)(atbuf[q]-'0');
                if(q+1<ATBUF_N&&atbuf[q+1]>='0'&&atbuf[q+1]<='9')csq=(uint8_t)(csq*10+(atbuf[q+1]-'0'));
            }
            break;
        }
    }
    return 1;
}

int main(void){
    /* Cold boot: OFF before enabling relay outputs. */
    PORTC|=(1<<RELAY6)|(1<<RELAY7)|(1<<RELAY8);
    DDRC|=(1<<RELAY6)|(1<<RELAY7)|(1<<RELAY8);
    relays_off();

    PORTC|=(1<<U2_OE)|(1<<U3_OE);
    DDRC|=(1<<U2_OE)|(1<<U3_OE);

    /* Critical compatibility with original board/modem circuitry. */
    PORTD|=(1<<PD3)|(1<<PD4)|(1<<PD5)|(1<<PD6)|(1<<PD7);
    DDRD|=(1<<PD3)|(1<<PD4)|(1<<PD5)|(1<<PD6)|(1<<PD7);
    DDRD&=~(1<<PD2);PORTD&=~(1<<PD2);

    linit();screen_P(PSTR("V2.2.8"),PSTR("E06 CODE"));dms(800);
    last_u2=read_u2();last_u3=read_u3();

    for(;;){
        uint8_t socket_failures=0;

        /* Full modem/GPRS init only when network layer is actually being rebuilt. */
        if(!modem_gprs_init()){
            screen_P(PSTR("E01 NET"),PSTR("FAIL"));
            dms(5000);
            continue;
        }

        for(;;){
            screen_P(PSTR("TCP"),PSTR("OPENING"));
            {
                uint8_t open_err=socket_open();
                if(!open_err)goto tcp_opened;
                screen_e6(open_err);
                socket_close();
                socket_failures++;
                dms(2000);

                /*
                 * Ordinary TCP reconnect must not restart the whole GPRS stack.
                 * After several consecutive socket-open failures, fall back to
                 * a full network init.
                 */
                if(socket_failures>=3U)break;
                continue;
            }
tcp_opened:

            socket_failures=0;
            screen_P(PSTR("TCP UP"),PSTR("WAIT AUTH"));

            authenticated=0;
            auth_stage=0;
            auth_scan_reset();
            pending_auth_tx=0;
            pending_initial_state=0;
            rx_len=0;
            rx_overflow=0;
            pending_text_cmd=0;
            auth_started_ms=clock_ms;
            last_state_ms=clock_ms;

            for(;;){
                /* RX has first priority. */
                if(!socket_read_once()){
                    screen_P(PSTR("E11 RX"),PSTR("PATH"));
                    dms(1800);
                    break;
                }

                /* SISR reply is drained now; only here may we issue SISW. */
                if(pending_auth_tx){
                    pending_auth_tx=0;
                    if(!send_auth()){
                        screen_P(PSTR("E09 AUTH"),PSTR("TX"));
                        dms(2500);
                        break;
                    }
                    auth_stage=1;
                    screen_P(PSTR("AUTH"),PSTR("SENT"));
                }

                if(pending_initial_state){
                    pending_initial_state=0;
                    if(!send_state()){
                        screen_P(PSTR("E12 TX"),PSTR("STATE"));
                        dms(2500);
                        break;
                    }
                    screen_P(PSTR("ONLINE"),PSTR("V2 READY"));
                }

                /*
                 * Now the SISR transaction is finished, so executing a command
                 * is safe: SET/GET/PING may issue one or more SISW writes.
                 */
                if(authenticated && pending_text_cmd){
                    if(!process_pending_text_command()){
                        screen_P(PSTR("E12 TX"),PSTR("CMD"));
                        dms(2000);
                        break;
                    }
                }

                if(!authenticated && elapsed_ms(auth_started_ms,AUTH_DIAG_TIMEOUT_MS)){
                    if(auth_stage==0){
                        screen_P(PSTR("E08 AUTH"),PSTR("NONCE"));
                    }else{
                        screen_P(PSTR("E10 AUTH"),PSTR("TIMEOUT"));
                    }
                    dms(2500);
                    break;
                }

                if(authenticated){
                    if(raw_inputs_changed()){
                        if(!send_state()){
                            screen_P(PSTR("E12 TX"),PSTR("STATE"));
                            dms(2000);
                            break;
                        }
                    }else if(elapsed_ms(last_state_ms,STATE_PERIOD_MS)){
                        if(!send_state()){
                            screen_P(PSTR("E12 TX"),PSTR("STATE"));
                            dms(2000);
                            break;
                        }
                    }
                }

                /*
                 * No AT^SISO? watchdog here.
                 * Socket loss is detected by SISR/SISW failure instead.
                 */
                dms(READ_POLL_MS);
            }

            authenticated=0;
            socket_close();

            /*
             * Reopen TCP on the existing GPRS context.
             * Relay outputs are intentionally untouched.
             */
            screen_P(PSTR("TCP"),PSTR("RECONNECT"));
            dms(1200);
        }
    }
}
