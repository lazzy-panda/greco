import {Button} from "@/components/ui/button";
import Image from "next/image"

export const Footer = () => {
    return (
        <footer className='hidden lg:block h-20 w-full border-t-2 border-slate-200 p-2'>
            <div className='max-w-screen-lg mx-auto flex items-center justify-evenly h-full'>
                <Button size='lg' variant='ghost' className='w-full'>
                    <Image
                        height={32}
                        width={40}
                        src='/flags/4x3/gr.svg'
                        alt='Flag'
                        className='mr-4 rounded-md'
                    />
                    Greek
                </Button>
                <Button size='lg' variant='ghost' className='w-full'>
                    <Image
                        height={32}
                        width={40}
                        src='/flags/4x3/in.svg'
                        alt='Flag'
                        className='mr-4 rounded-md'
                    />
                    Sanskrit
                </Button>
                <Button size='lg' variant='ghost' className='w-full'>
                    <Image
                        height={32}
                        width={40}
                        src='/flags/4x3/Flag_of_Tibet.svg'
                        alt='Flag'
                        className='mr-4 rounded-md'
                    />
                    Tibetan
                </Button>
            </div>
        </footer>
    )
}
